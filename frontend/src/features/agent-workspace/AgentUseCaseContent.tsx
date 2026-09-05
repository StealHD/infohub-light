const examples = [
  { title: '快捷输入：@ 与 /', steps: '输入 @ 选择 Skill 或材料，输入 / 查看命令；上下键选择，Enter 执行，Esc 关闭候选，Tab 正常切换焦点。/skills 把列表输出到对话中，输入框不会进入技能子菜单。', result: '命令结果显示在当前对话中：/status、/help 查看信息，/model、/reasoning 列出选项，/new、/worktree 等待行内确认。选 Skill 不发送，点击发送才核验并调用；来源快照禁止同时调用 Skill。' },
  { title: '对话：整理阅读结论', steps: '在信息流选择一篇文章加入 Agent，再问“总结主要结论，并指出证据不足的地方”。', result: '在对话中看到回答和来源；发送前可以修改问题。' },
  { title: '上下文：核对本次附带的材料', steps: '打开“上下文”，查看从信息流带来的文章或任务，移除不相关的条目。', result: '只改变待发送材料，不会发送消息，也不会删除原文章。' },
  { title: 'Worktree：独立修改项目', steps: '点击侧栏分支图标，选择已注册项目和 main 分支，输入“为登录表单补充校验和测试”，核对后创建。', result: 'Gateway 创建独立工作目录与子会话，父对话保留。此操作会真实修改项目，需要你确认。' },
  { title: 'Tasks：跟进后台执行', steps: '打开“Tasks”，按运行状态筛选，点任务查看进度和结果；需要停止时再确认取消。', result: '看到当前会话树的后台任务。没有记录时不代表聊天不可用；取消不会撤销已完成的修改。' },
  { title: 'Artifacts：查看输出文件', steps: '任务产生报告后，打开“Artifacts”，选择对应会话，预览 result.md 或下载文件。', result: '查看 Gateway 明确登记的产物；聊天中提到的路径不会自动成为产物。HTML、SVG 等文件仅供下载。' },
  { title: 'Skills：了解与扩展 Agent 能力', steps: '打开“Skills”，点击详情查看用途与缺失条件。已就绪的 Skill 可在对话任务中由 Agent 按需使用。', result: '查看无需管理授权。启停、上传安装需临时授权并再次确认；授权本身不会执行操作。' },
  { title: 'Automations：定时重复任务', steps: '例如创建“每天阅读摘要”，选择 Cron“0 9 * * *”和 Asia/Shanghai，填写“整理今日阅读要点”。', result: '新建默认停用；核对并启用后由 Gateway 定时执行。关闭网页仍会继续，可查看运行记录或停用。' },
]

export function AgentUseCaseContent() {
  return <div className="grid gap-4">
    <p className="type-body text-muted">以下是操作示例，不是你的实际任务或数据。阅读示例不会连接 Gateway 或执行操作；可用功能取决于当前 Gateway。</p>
    {examples.map((example) => <section key={example.title} className="grid gap-2 border-b border-separator pb-4">
      <h3 className="type-page-title">{example.title}</h3>
      <p className="type-body">{example.steps}</p>
      <p className="type-meta text-muted">预期结果：{example.result}</p>
    </section>)}
  </div>
}
