import { type Browser, expect, type Page, test } from "@playwright/test";

// 账号由 backend/scripts/e2e_server.py 创建
const USER = { username: "e2euser", password: "e2e-user-pass" };
const ADMIN = { username: "e2eadmin", password: "e2e-admin-pass" };

async function login(page: Page, account: { username: string; password: string }) {
  await page.goto("/login/");
  await page.getByLabel("用户名").fill(account.username);
  await page.getByLabel("密码").fill(account.password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /你好/ })).toBeVisible();
}

async function newPage(browser: Browser) {
  const context = await browser.newContext();
  return context.newPage();
}

test("登录后看到今天页，退出后回到登录页", async ({ page }) => {
  await login(page, USER);
  await page.getByRole("link", { name: /我的/ }).click();
  await page.getByRole("button", { name: "退出登录" }).click();
  await page.getByRole("button", { name: "退出", exact: true }).click();
  await expect(page.getByRole("heading", { name: "HealthOS 登录" })).toBeVisible();
});

test("直接填写记一餐，再修改份量保存，然后删除并撤销", async ({ page }) => {
  await login(page, USER);

  // 记一餐（不用 AI）
  await page.getByRole("button", { name: "记一笔" }).click();
  await page.getByRole("button", { name: /饮食/ }).click();
  await page.getByRole("button", { name: /不用 AI，直接填写/ }).click();
  await page.getByLabel("食物", { exact: true }).fill("e2e米饭");
  await page.getByRole("textbox", { name: "单位" }).fill("碗");
  await page.getByRole("button", { name: "保存" }).click();
  // 测试环境没有 AI（也没同意 AI）：自动估算失败并提示，再点一次保存就按现有数值保存
  await expect(page.locator("form p.error").first()).toBeVisible();
  await page.getByRole("button", { name: "保存" }).click();
  await expect(page.getByRole("status")).toHaveText(/饮食已记录/);

  // 修改份量并保存：修改请求用 POST + X-HTTP-Method-Override 发送
  await page.getByRole("button", { name: /e2e米饭/ }).first().click();
  await page.getByRole("spinbutton", { name: "份量" }).fill("1.5");
  const patch = page.waitForRequest((r) => /\/api\/meals\/[0-9a-f-]+$/.test(r.url()) && r.method() === "POST");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await patch).headers()["x-http-method-override"]).toBe("PATCH");
  await expect(page.getByRole("status")).toHaveText(/已保存修改/);
  const meals = await page.request.get("/api/meals").then((r) => r.json());
  expect(meals.find((m: { food_items: { name: string }[] }) => m.food_items[0].name === "e2e米饭").food_items[0].quantity).toBe(1.5);

  // 删除后撤销
  await page.getByRole("button", { name: /e2e米饭/ }).first().click();
  await page.getByRole("button", { name: "删除这条记录" }).click();
  await page.getByRole("button", { name: "删除", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("已删除");
  await expect(page.getByRole("button", { name: /e2e米饭/ })).toHaveCount(0);
  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByRole("status")).toHaveText(/已恢复/);
  await expect(page.getByRole("button", { name: /e2e米饭/ })).toHaveCount(1);
});

test("管理员生成邀请码，新用户用链接注册并自动登录", async ({ page, browser }) => {
  await login(page, ADMIN);
  await page.goto("/invites/");
  await page.getByLabel(/备注/).fill("e2e");
  await page.getByRole("button", { name: "生成邀请码" }).click();
  const code = (await page.locator(".invite-code").innerText()).trim();
  expect(code).toMatch(/^[A-Z2-9]{4}-[A-Z2-9]{4}$/);

  const guest = await newPage(browser);
  await guest.goto(`/register/?code=${code}`);
  await expect(guest.getByLabel("邀请码")).toHaveValue(code);
  await guest.getByLabel(/^用户名/).fill("e2enew");
  await guest.getByLabel(/显示名称/).fill("新家人");
  await guest.getByLabel(/^密码/).fill("new-pass-123");
  await guest.getByLabel("再输入一次密码").fill("new-pass-123");
  await guest.getByRole("button", { name: "注册并登录" }).click();
  await expect(guest.getByRole("heading", { level: 1, name: /你好，新家人/ })).toBeVisible();

  // 同一个邀请码不能再用
  const other = await newPage(browser);
  await other.goto(`/register/?code=${code}`);
  await other.getByLabel(/^用户名/).fill("e2enew2");
  await other.getByLabel(/^密码/).fill("new-pass-123");
  await other.getByLabel("再输入一次密码").fill("new-pass-123");
  await other.getByRole("button", { name: "注册并登录" }).click();
  await expect(other.locator("p.error")).toContainText("邀请码无效");
});

test("管理员重置用户密码后，用户用临时密码登录", async ({ page, browser }) => {
  await login(page, ADMIN);
  await page.goto("/users/");
  const row = page.locator(".entry", { hasText: "e2euser" });
  await row.getByRole("button", { name: "重置密码" }).click();
  await page.getByRole("button", { name: "重置", exact: true }).click();
  const temporary = (await page.locator(".invite-code").innerText()).trim();
  expect(temporary).toHaveLength(10);

  const user = await newPage(browser);
  await login(user, { username: USER.username, password: temporary });

  // 改回原密码，避免影响其他用例
  await user.goto("/password/");
  await user.getByLabel("当前密码").fill(temporary);
  await user.getByLabel(/^新密码/).fill(USER.password);
  await user.getByLabel("再输入一次新密码").fill(USER.password);
  await user.getByRole("button", { name: "保存" }).click();
  await expect(user.getByRole("status")).toContainText("密码已修改");
});
