"""好友、共餐邀请和消息页。

共餐的做法：发送时把这一餐存成快照（菜品 + 时间 + 照片副本，不含备注），
对方接受后在自己的账户里新建一条普通饮食记录。两边的记录互相独立；
发送方之后修改原记录，会刷新快照并提示接收方是否同步。
"""

import hashlib
import io
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select

from app.audit import commit_with_tenant_context
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.models import FoodItem, Friendship, Meal, MealPhoto, MealShare, User
from app.photos import _thumbnail
from app.records import (
    FoodItemIn,
    MealOut,
    _aware,
    _meal_out,
    _meal_photo_ids,
    _replace_food_items,
)
from app.repositories import get_owned_meal

router = APIRouter(prefix="/api", tags=["friends"])

SHARE_EXPIRES = timedelta(days=7)
DAILY_FRIEND_REQUESTS = 20
MealType = Literal["breakfast", "lunch", "dinner", "snack"]


class UserBrief(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str


class FriendOut(BaseModel):
    user: UserBrief
    since: datetime | None


class FriendRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=32)


class FriendRequestOut(BaseModel):
    # accepted：对方之前也向你发过请求，直接成为好友
    status: Literal["pending", "accepted"]


class ShareSnapshot(BaseModel):
    eaten_at: datetime
    meal_type: str
    food_items: list[FoodItemIn]


class ShareOut(ShareSnapshot):
    photo_count: int
    ratio: float
    created_meal_id: uuid.UUID | None
    update_pending: bool


class MessageOut(BaseModel):
    id: uuid.UUID
    kind: Literal["friend_request", "meal_share"]
    direction: Literal["in", "out"]
    # 好友请求：pending / accepted / declined；共餐：另有 cancelled / expired
    status: str
    other: UserBrief
    created_at: datetime
    responded_at: datetime | None
    share: ShareOut | None = None


class MessagesOut(BaseModel):
    unread: int
    items: list[MessageOut]


class UnreadOut(BaseModel):
    unread: int


class ShareIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    friend_ids: list[uuid.UUID] = Field(min_length=1, max_length=10)
    # 每位好友吃了整餐的多少
    ratio: float = Field(gt=0, le=1)
    # 同时把自己的这条记录按比例缩小（原记录是整餐时用）
    my_ratio: float | None = Field(default=None, gt=0, le=1)


class ShareResultOut(BaseModel):
    shared: int
    meal: MealOut


class AcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ratio: float = Field(gt=0, le=1)
    eaten_at: datetime
    meal_type: MealType
    notes: str | None = Field(default=None, max_length=2000)
    food_items: list[FoodItemIn] = Field(min_length=1, max_length=50)

    _validate_eaten_at = field_validator("eaten_at")(_aware)


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apply: bool


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pair_key(a: uuid.UUID, b: uuid.UUID) -> str:
    low, high = sorted((str(a), str(b)))
    return f"{low}:{high}"


def _brief(user: User) -> UserBrief:
    return UserBrief(id=user.id, username=user.username, display_name=user.display_name)


def _users(db: DbSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, User]:
    if not ids:
        return {}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}


def _are_friends(db: DbSession, a: uuid.UUID, b: uuid.UUID) -> bool:
    return (
        db.scalar(
            select(Friendship.id).where(Friendship.pair_key == _pair_key(a, b), Friendship.status == "accepted")
        )
        is not None
    )


def _share_dir(share_id: uuid.UUID) -> Path:
    return get_settings().photo_dir / "shares" / str(share_id)


def _remove_share_files(share_id: uuid.UUID) -> None:
    shutil.rmtree(_share_dir(share_id), ignore_errors=True)


def _expired(share: MealShare) -> bool:
    return share.status == "pending" and share.created_at < _now() - SHARE_EXPIRES


def scale_items(items: list[FoodItemIn], ratio: float) -> list[FoodItemIn]:
    if ratio == 1:
        return list(items)

    def part(value: float | None, digits: int = 1) -> float | None:
        return None if value is None else round(value * ratio, digits)

    return [
        item.model_copy(
            update={
                "quantity": max(round(item.quantity * ratio, 2), 0.01),
                "kcal": part(item.kcal),
                "protein_g": part(item.protein_g),
                "carbs_g": part(item.carbs_g),
                "fat_g": part(item.fat_g),
                "fiber_g": part(item.fiber_g),
                "sugar_g": part(item.sugar_g),
                "sodium_mg": part(item.sodium_mg, 0),
            }
        )
        for item in items
    ]


def _meal_items(db: DbSession, meal: Meal) -> list[FoodItemIn]:
    rows = db.scalars(
        select(FoodItem).where(FoodItem.meal_id == meal.id, FoodItem.user_id == meal.user_id).order_by(FoodItem.name)
    )
    return [FoodItemIn.model_validate(row, from_attributes=True) for row in rows]


def _snapshot(meal: Meal, full_items: list[FoodItemIn]) -> str:
    return ShareSnapshot(eaten_at=meal.eaten_at, meal_type=meal.meal_type, food_items=full_items).model_dump_json()


def _active_shares_of(db: DbSession, user_id: uuid.UUID, meal_id: uuid.UUID) -> list[MealShare]:
    return list(
        db.scalars(
            select(MealShare)
            .where(
                MealShare.from_user_id == user_id,
                MealShare.source_meal_id == meal_id,
                MealShare.status.in_(("pending", "accepted")),
            )
            .order_by(MealShare.created_at.desc())
        )
    )


def _share_out(share: MealShare) -> ShareOut:
    snapshot = ShareSnapshot.model_validate_json(share.snapshot_json)
    return ShareOut(
        **snapshot.model_dump(),
        photo_count=share.photo_count,
        ratio=share.ratio,
        created_meal_id=share.created_meal_id,
        update_pending=share.update_pending,
    )


# ---------- 好友 ----------


@router.get("/friends")
def list_friends(user: CurrentUser, db: DbSession) -> list[FriendOut]:
    rows = list(
        db.scalars(
            select(Friendship).where(
                Friendship.status == "accepted",
                or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id),
            )
        )
    )
    others = {r.addressee_id if r.requester_id == user.id else r.requester_id: r for r in rows}
    users = _users(db, set(others))
    friends = [FriendOut(user=_brief(users[uid]), since=row.responded_at) for uid, row in others.items() if uid in users]
    return sorted(friends, key=lambda f: f.user.display_name)


@router.post("/friends/requests", status_code=status.HTTP_201_CREATED)
def send_friend_request(body: FriendRequestIn, user: CurrentUser, db: DbSession) -> FriendRequestOut:
    recent = db.scalar(
        select(func.count())
        .select_from(Friendship)
        .where(Friendship.requester_id == user.id, Friendship.created_at >= _now() - timedelta(days=1))
    )
    if (recent or 0) >= DAILY_FRIEND_REQUESTS:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "今天发出的好友请求太多了，明天再试")
    target = db.scalar(select(User).where(User.username == body.username.strip().lower()))
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "没有这个用户名")
    if target.id == user.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能添加自己为好友")
    row = db.scalar(select(Friendship).where(Friendship.pair_key == _pair_key(user.id, target.id)))
    if row is not None and row.status == "accepted":
        raise HTTPException(status.HTTP_409_CONFLICT, "你们已经是好友了")
    if row is not None and row.status == "pending":
        if row.requester_id == user.id:
            raise HTTPException(status.HTTP_409_CONFLICT, "已发送过请求，等对方确认")
        # 对方也向你发过请求，直接成为好友
        row.status = "accepted"
        row.responded_at = _now()
        commit_with_tenant_context(db, user.id)
        return FriendRequestOut(status="accepted")
    if row is None:
        row = Friendship(pair_key=_pair_key(user.id, target.id))
        db.add(row)
    # 被拒绝过的可以重新发
    row.requester_id = user.id
    row.addressee_id = target.id
    row.status = "pending"
    row.created_at = _now()
    row.responded_at = None
    commit_with_tenant_context(db, user.id)
    return FriendRequestOut(status="pending")


def _incoming_request(db: DbSession, user: CurrentUser, request_id: uuid.UUID) -> Friendship:
    row = db.scalar(
        select(Friendship).where(
            Friendship.id == request_id, Friendship.addressee_id == user.id, Friendship.status == "pending"
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "好友请求不存在或已处理")
    return row


@router.post("/friends/requests/{request_id}/accept", status_code=status.HTTP_204_NO_CONTENT)
def accept_friend_request(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    row = _incoming_request(db, user, request_id)
    row.status = "accepted"
    row.responded_at = _now()
    commit_with_tenant_context(db, user.id)


@router.post("/friends/requests/{request_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_friend_request(request_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    row = _incoming_request(db, user, request_id)
    row.status = "declined"
    row.responded_at = _now()
    commit_with_tenant_context(db, user.id)


@router.delete("/friends/{friend_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_friend(friend_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    """删除好友，或撤回自己发出的好友请求。双方之间未处理的共餐邀请一并取消。"""
    row = db.scalar(select(Friendship).where(Friendship.pair_key == _pair_key(user.id, friend_id)))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "不是好友")
    db.delete(row)
    pending = list(
        db.scalars(
            select(MealShare).where(
                MealShare.status == "pending",
                or_(
                    (MealShare.from_user_id == user.id) & (MealShare.to_user_id == friend_id),
                    (MealShare.from_user_id == friend_id) & (MealShare.to_user_id == user.id),
                ),
            )
        )
    )
    for share in pending:
        share.status = "cancelled"
        share.responded_at = _now()
    commit_with_tenant_context(db, user.id)
    for share in pending:
        _remove_share_files(share.id)


# ---------- 消息 ----------


def _unread(db: DbSession, user_id: uuid.UUID) -> int:
    requests = db.scalar(
        select(func.count())
        .select_from(Friendship)
        .where(Friendship.addressee_id == user_id, Friendship.status == "pending")
    )
    shares = db.scalar(
        select(func.count())
        .select_from(MealShare)
        .where(
            MealShare.to_user_id == user_id,
            or_(
                (MealShare.status == "pending") & (MealShare.created_at >= _now() - SHARE_EXPIRES),
                (MealShare.status == "accepted") & MealShare.update_pending,
            ),
        )
    )
    return (requests or 0) + (shares or 0)


@router.get("/messages/unread-count")
def unread_count(user: CurrentUser, db: DbSession) -> UnreadOut:
    return UnreadOut(unread=_unread(db, user.id))


@router.get("/messages")
def list_messages(user: CurrentUser, db: DbSession) -> MessagesOut:
    requests = list(
        db.scalars(
            select(Friendship)
            .where(or_(Friendship.requester_id == user.id, Friendship.addressee_id == user.id))
            .order_by(Friendship.created_at.desc())
            .limit(50)
        )
    )
    shares = list(
        db.scalars(
            select(MealShare)
            .where(or_(MealShare.from_user_id == user.id, MealShare.to_user_id == user.id))
            .order_by(MealShare.created_at.desc())
            .limit(50)
        )
    )
    others = {r.addressee_id if r.requester_id == user.id else r.requester_id for r in requests}
    others |= {s.to_user_id if s.from_user_id == user.id else s.from_user_id for s in shares}
    users = _users(db, others)
    items: list[MessageOut] = []
    for r in requests:
        outgoing = r.requester_id == user.id
        other = users.get(r.addressee_id if outgoing else r.requester_id)
        if other is None:
            continue
        items.append(
            MessageOut(
                id=r.id,
                kind="friend_request",
                direction="out" if outgoing else "in",
                status=r.status,
                other=_brief(other),
                created_at=r.created_at,
                responded_at=r.responded_at,
            )
        )
    for s in shares:
        outgoing = s.from_user_id == user.id
        other = users.get(s.to_user_id if outgoing else s.from_user_id)
        if other is None:
            continue
        items.append(
            MessageOut(
                id=s.id,
                kind="meal_share",
                direction="out" if outgoing else "in",
                status="expired" if _expired(s) else s.status,
                other=_brief(other),
                created_at=s.created_at,
                responded_at=s.responded_at,
                share=_share_out(s),
            )
        )
    items.sort(key=lambda m: m.created_at, reverse=True)
    return MessagesOut(unread=_unread(db, user.id), items=items)


# ---------- 共餐 ----------


@router.post("/meals/{meal_id}/shares", status_code=status.HTTP_201_CREATED)
def share_meal(meal_id: uuid.UUID, body: ShareIn, user: CurrentUser, db: DbSession) -> ShareResultOut:
    meal = get_owned_meal(db, user.id, meal_id)
    if meal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    friend_ids = list(dict.fromkeys(body.friend_ids))
    for friend_id in friend_ids:
        if not _are_friends(db, user.id, friend_id):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "只能分享给好友")
    active = _active_shares_of(db, user.id, meal.id)
    already = {share.to_user_id for share in active}
    # 之前分享时可能已把自己的记录缩小过，先还原成整餐
    current_ratio = active[0].source_ratio if active else 1.0
    full_items = scale_items(_meal_items(db, meal), 1 / current_ratio)
    new_ratio = body.my_ratio if body.my_ratio is not None else current_ratio
    photo_paths = []
    for photo_id in _meal_photo_ids(db, meal):
        photo = db.get(MealPhoto, photo_id)
        if photo is not None:
            path = get_settings().photo_dir / photo.storage_key
            if path.is_file():
                photo_paths.append(path)
    snapshot = _snapshot(meal, full_items)
    created: list[MealShare] = []
    for friend_id in friend_ids:
        if friend_id in already:
            continue
        share = MealShare(
            id=uuid.uuid4(),
            from_user_id=user.id,
            to_user_id=friend_id,
            source_meal_id=meal.id,
            snapshot_json=snapshot,
            photo_count=len(photo_paths),
            ratio=body.ratio,
            source_ratio=new_ratio,
            status="pending",
            created_at=_now(),
        )
        db.add(share)
        created.append(share)
    if created and new_ratio != current_ratio:
        _replace_food_items(db, meal, user.id, scale_items(full_items, new_ratio))
        for share in active:
            share.source_ratio = new_ratio
    # 照片复制一份给邀请用；接受后转成对方自己的照片，拒绝/撤回时删除
    try:
        for share in created:
            target = _share_dir(share.id)
            target.mkdir(parents=True, exist_ok=True)
            for index, path in enumerate(photo_paths):
                shutil.copyfile(path, target / f"{index}.jpg")
        commit_with_tenant_context(db, user.id)
    except Exception:
        for share in created:
            _remove_share_files(share.id)
        raise
    db.refresh(meal)
    return ShareResultOut(shared=len(created), meal=_meal_out(db, meal))


def _share_for(db: DbSession, share_id: uuid.UUID, *, to_user: uuid.UUID | None = None, from_user: uuid.UUID | None = None) -> MealShare:
    statement = select(MealShare).where(MealShare.id == share_id)
    if to_user is not None:
        statement = statement.where(MealShare.to_user_id == to_user)
    if from_user is not None:
        statement = statement.where(MealShare.from_user_id == from_user)
    share = db.scalar(statement)
    if share is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "邀请不存在")
    return share


def _require_pending(share: MealShare) -> None:
    if share.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "这条邀请已处理")
    if _expired(share):
        raise HTTPException(status.HTTP_409_CONFLICT, "这条邀请已过期")


@router.get("/meal-shares/{share_id}/photos/{index}", response_class=FileResponse)
def get_share_photo(
    share_id: uuid.UUID,
    index: int,
    user: CurrentUser,
    db: DbSession,
    size: Literal["full", "thumb"] = "full",
) -> FileResponse:
    share = db.scalar(
        select(MealShare).where(
            MealShare.id == share_id, or_(MealShare.from_user_id == user.id, MealShare.to_user_id == user.id)
        )
    )
    if share is None or not 0 <= index < share.photo_count:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    path = _share_dir(share.id) / f"{index}.jpg"
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    if size == "thumb":
        path = _thumbnail(path)
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


def _adopt_photos(db: DbSession, user: CurrentUser, share: MealShare, meal: Meal) -> list[Path]:
    """把邀请里的照片变成接收方自己的照片并关联到新记录，返回新写入的文件（提交失败时删除）。"""
    settings = get_settings()
    written: list[Path] = []
    photo_ids: list[uuid.UUID] = []
    for index in range(share.photo_count):
        source = _share_dir(share.id) / f"{index}.jpg"
        if not source.is_file():
            continue
        data = source.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        existing = db.scalar(select(MealPhoto).where(MealPhoto.user_id == user.id, MealPhoto.sha256 == digest))
        if existing is not None:
            if existing.meal_id is None:
                existing.meal_id = meal.id
                photo_ids.append(existing.id)
            continue
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
        photo_id = uuid.uuid4()
        storage_key = f"{user.id}/{photo_id}.jpg"
        target = settings.photo_dir / storage_key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(target)
        db.add(
            MealPhoto(
                id=photo_id,
                user_id=user.id,
                meal_id=meal.id,
                storage_key=storage_key,
                sha256=digest,
                content_type="image/jpeg",
                byte_size=len(data),
                width=width,
                height=height,
            )
        )
        photo_ids.append(photo_id)
    db.flush()
    meal.photo_id = photo_ids[0] if photo_ids else None
    return written


@router.post("/meal-shares/{share_id}/accept", status_code=status.HTTP_201_CREATED)
def accept_share(share_id: uuid.UUID, body: AcceptIn, user: CurrentUser, db: DbSession) -> MealOut:
    share = _share_for(db, share_id, to_user=user.id)
    _require_pending(share)
    meal = Meal(
        user_id=user.id,
        eaten_at=body.eaten_at,
        meal_type=body.meal_type,
        status="confirmed",
        notes=body.notes,
        shared_from_id=share.id,
    )
    db.add(meal)
    db.flush()
    _replace_food_items(db, meal, user.id, body.food_items)
    written: list[Path] = []
    try:
        written = _adopt_photos(db, user, share, meal)
        share.status = "accepted"
        share.ratio = body.ratio
        share.created_meal_id = meal.id
        share.responded_at = _now()
        commit_with_tenant_context(db, user.id)
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    _remove_share_files(share.id)
    db.refresh(meal)
    return _meal_out(db, meal)


@router.post("/meal-shares/{share_id}/decline", status_code=status.HTTP_204_NO_CONTENT)
def decline_share(share_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    share = _share_for(db, share_id, to_user=user.id)
    if share.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "这条邀请已处理")
    share.status = "declined"
    share.responded_at = _now()
    commit_with_tenant_context(db, user.id)
    _remove_share_files(share.id)


@router.post("/meal-shares/{share_id}/cancel", status_code=status.HTTP_204_NO_CONTENT)
def cancel_share(share_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    share = _share_for(db, share_id, from_user=user.id)
    if share.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "对方已处理，不能撤回")
    share.status = "cancelled"
    share.responded_at = _now()
    commit_with_tenant_context(db, user.id)
    _remove_share_files(share.id)


@router.post("/meal-shares/{share_id}/sync", status_code=status.HTTP_204_NO_CONTENT)
def sync_share(share_id: uuid.UUID, body: SyncIn, user: CurrentUser, db: DbSession) -> None:
    """发送方改过这一餐后：apply=true 按自己的份额同步菜品和时间，false 忽略这次更新。"""
    share = _share_for(db, share_id, to_user=user.id)
    if share.status != "accepted" or not share.update_pending:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有需要同步的更新")
    meal = get_owned_meal(db, user.id, share.created_meal_id) if body.apply and share.created_meal_id else None
    if meal is not None:
        snapshot = ShareSnapshot.model_validate_json(share.snapshot_json)
        meal.eaten_at = snapshot.eaten_at
        meal.meal_type = snapshot.meal_type
        _replace_food_items(db, meal, user.id, scale_items(snapshot.food_items, share.ratio))
    share.update_pending = False
    commit_with_tenant_context(db, user.id)


def notify_meal_updated(db: DbSession, user: User, meal: Meal) -> None:
    """发送方改了原记录：刷新快照；已接受的邀请标记为有更新，提示对方是否同步。"""
    shares = _active_shares_of(db, user.id, meal.id)
    if not shares:
        return
    snapshot = _snapshot(meal, scale_items(_meal_items(db, meal), 1 / shares[0].source_ratio))
    for share in shares:
        if share.snapshot_json == snapshot:
            continue
        share.snapshot_json = snapshot
        if share.status == "accepted":
            share.update_pending = True
    commit_with_tenant_context(db, user.id)
