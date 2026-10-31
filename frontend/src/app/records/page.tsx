import Link from "next/link";

export default function RecordsPage() {
  return (
    <div className="card stack">
      <h1>手工健康记录</h1>
      <p>所有记录默认仅本人可见。即使以后 AI 不可用，手工记录仍然可以使用。</p>
      <Link href="/meals/">饮食记录</Link>
      <Link href="/exercises/">运动记录</Link>
      <Link href="/sleeps/">睡眠记录</Link>
      <Link href="/">返回首页</Link>
    </div>
  );
}
