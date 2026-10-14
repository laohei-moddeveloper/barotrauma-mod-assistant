using System;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Xml.Linq;
using Microsoft.Win32;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private static string Storage => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BaroEditor");
        private bool CanDiscard()
        {
            CommitInspector(); return !Model.ProjectDirty || Confirm("载入其他文件会放弃当前草稿及未保存布局。\n继续？");
        }
        private void NewFile()
        {
            if (!CanDiscard()) return; Model.Load(new EventDocument(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets/example.xml")))); projectPath = null; ResetView(); SetStatus("示例已载入 · 默认导出副本");
        }
        private void OpenFile()
        {
            var dialog = new OpenFileDialog { Title = "导入事件 XML 或 BaroEditor 工程", Filter = "事件与工程|*.xml;*.baroeditor|事件 XML|*.xml|BaroEditor 工程|*.baroeditor", CheckFileExists = true };
            if (dialog.ShowDialog(this) == true && CanDiscard()) LoadPath(dialog.FileName);
        }
        private void OpenVanilla()
        {
            var dialog = new OpenFileDialog { Title = "选择原版或模组的事件 XML（读取文件，不运行游戏）", Filter = "事件 XML|*.xml", CheckFileExists = true };
            string known = "D:/steam/steamapps/common/Barotrauma/Content/Events"; if (Directory.Exists(known)) dialog.InitialDirectory = Path.GetFullPath(known);
            if (dialog.ShowDialog(this) == true && CanDiscard()) LoadPath(dialog.FileName);
        }
        private void LoadPath(string path)
        {
            if (Path.GetExtension(path).Equals(".baroeditor", StringComparison.OrdinalIgnoreCase)) { Model.ReadProject(path); projectPath = path; }
            else { Model.Load(EventDocument.Read(path)); projectPath = null; }
            ResetView(); SetStatus("已载入 " + Path.GetFileName(path) + " · 原文件保留");
        }
        private void ResetView()
        {
            building = true; fields.Clear(); nodeSearch.Text = ""; propertySearch.Text = ""; linkSource = null;
            foreach (var key in new[] { "nodes", "properties" }) if (delays.TryGetValue(key, out var timer)) { timer.Stop(); delays.Remove(key); }
            building = false; graphScroll.ScrollToHorizontalOffset(0); graphScroll.ScrollToVerticalOffset(0); RefreshAll();
        }
        private void SaveProject()
        {
            CommitInspector(); var dialog = new SaveFileDialog { Title = "保存工程（XML 草稿与节点布局）", Filter = "BaroEditor 工程|*.baroeditor", DefaultExt = ".baroeditor", FileName = projectPath == null ? "event.baroeditor" : Path.GetFileName(projectPath), OverwritePrompt = true };
            if (projectPath != null) dialog.InitialDirectory = Path.GetDirectoryName(projectPath);
            if (dialog.ShowDialog(this) != true) return;
            if (!Path.GetExtension(dialog.FileName).Equals(".baroeditor", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("工程文件请使用 .baroeditor 扩展名；事件 XML 请用导出功能。");
            ProtectPath(dialog.FileName); Model.SaveProject(dialog.FileName); projectPath = dialog.FileName; RefreshHeader(); SetStatus("工程已保存 · 可继续恢复布局和 XML 草稿");
        }
        private void ExportXml()
        {
            CommitInspector(); string directory = Path.Combine(Storage, "Exports"); Directory.CreateDirectory(directory);
            var dialog = new SaveFileDialog { Title = "导出 XML 副本", Filter = "事件 XML|*.xml", DefaultExt = ".xml", FileName = "event.xml", InitialDirectory = directory, OverwritePrompt = true };
            if (dialog.ShowDialog(this) != true) return; ProtectPath(dialog.FileName);
            if (Model.Document.SourcePath != null && Path.GetFullPath(dialog.FileName).Equals(Path.GetFullPath(Model.Document.SourcePath), StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("导出请选择新的文件名。覆盖原文件请使用高级操作。");
            string output = Model.Document.SaveCopy(Path.GetDirectoryName(dialog.FileName), Path.GetFileName(dialog.FileName)); RefreshHeader(); SetStatus("XML 副本已导出：" + output);
        }
        private void CopyXml(bool full)
        {
            CommitInspector(); XElement node = Model.Current;
            if (!full) { node = node.AncestorsAndSelf().FirstOrDefault(e => e.Name.LocalName is "ScriptedEvent" or "TraitorEvent"); if (node == null) throw new InvalidOperationException("请先选择事件或事件内的节点。"); }
            Clipboard.SetText(EventDocument.PrettyXml(full ? (XNode)Model.Document.Xml : node)); SetStatus("XML 已复制 · 带换行与缩进"); RefreshHeader();
        }
        private static void ProtectPath(string path)
        {
            string value = Path.GetFullPath(path).Replace('\\', '/');
            if (value.Contains("/steamapps/workshop/content/", StringComparison.OrdinalIgnoreCase) || value.Contains("/Barotrauma/Content/", StringComparison.OrdinalIgnoreCase) || value.Contains("/Barotrauma/DLC/", StringComparison.OrdinalIgnoreCase)) throw new InvalidOperationException("原版资源与工坊缓存保持只读，请写入自己的模组项目。");
        }
        private void OverwriteSource()
        {
            CommitInspector(); if (Model.Document.SourcePath == null) throw new InvalidOperationException("此草稿没有可覆盖的源文件；请导出副本。工程内草稿不会自动读取原文件。"); ProtectPath(Model.Document.SourcePath);
            if (!Confirm("覆盖源文件：\n" + Model.Document.SourcePath + "\n\n将先备份原始字节，再检查外部修改。确认覆盖？")) return;
            Model.Document.OverwriteSource(Path.Combine(Storage, "Backups")); RefreshHeader(); SetStatus("源文件已保存 · 原始备份位于 " + Path.Combine(Storage, "Backups"));
        }
        private void ImportPasted()
        {
            if (!CanDiscard()) return; TextDialog("粘贴事件 XML", "", xml => { Model.Load(new EventDocument(xml)); projectPath = null; ResetView(); }, true, "在这里粘贴 XML；应用前不会读取剪贴板，也不会执行事件。");
        }
        private void ShowTools()
        {
            var menu = new ContextMenu { Background = panel, Foreground = ink };
            foreach (var (label, action) in new (string, Action)[] { ("粘贴导入 XML", ImportPasted), ("查找文件中的事件", FindEvent), ("编辑子树 XML", EditXml), ("高级：覆盖本地源文件", OverwriteSource), ("使用与交互说明", ShowHelp) })
            { var item = new MenuItem { Header = label }; item.Click += (_, _) => Safe(action); menu.Items.Add(item); }
            menu.PlacementTarget = this; menu.IsOpen = true;
        }
        private void FindEvent()
        {
            CommitInspector(); var dialog = Dialog("查找文件中的事件", 560); var root = Rows(GridLength.Auto, new GridLength(1, GridUnitType.Star), GridLength.Auto); root.Margin = new Thickness(18); dialog.Content = root;
            var choices = Model.Document.EventEntries().Select(e => new EventChoice { Caption = EventDocument.Attribute(e.Node, "identifier") + " / " + EditorText.Node(e.Node.Name.LocalName), Path = e.Path }).ToArray();
            var list = new ListBox { Background = panel, Foreground = ink, BorderBrush = line, DisplayMemberPath = "Caption" };
            var accept = Btn("选择事件", () => { if (list.SelectedItem is EventChoice choice) { Model.SetScope(choice.Path); RefreshAll(); dialog.Close(); } }, true); accept.IsEnabled = false;
            void Filter(string query) { list.ItemsSource = choices.Where(c => EditorText.Matches(c.Caption, query)).Take(100).ToArray(); list.SelectedIndex = list.Items.Count > 0 ? 0 : -1; }
            var search = Search("中文名称或事件标识符；最多显示 100 个，请细化搜索", Filter, "dialog"); At(root, search); At(root, list, 1); list.SelectionChanged += (_, _) => accept.IsEnabled = list.SelectedItem != null;
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) }; buttons.Children.Add(Btn("取消", dialog.Close)); buttons.Children.Add(accept); At(root, buttons, 2); Filter(""); dialog.ShowDialog();
        }
        private void ShowHelp() => MessageBox.Show(this,
            "所有原版动作和 XML 容器都可在画布编辑。\n\n• 动作库：拖入节点或空白画布添加；点击按当前上下文添加。\n• 节点：拖动改变布局；双击编辑文本或 XML；右侧编辑全部属性。\n• 连线：点击右侧输出圆点，选择分支，再点击目标左侧输入圆点。下一动作按同级 XML 顺序连接。\n• 剧本卡片：同级节点拖动排序；跨分支用画布连接。\n• 拖动空白画布平移；中键或空格 + 拖动也可平移。Ctrl + 滚轮围绕指针缩放；全图显示概览，定位恢复可读比例。\n• 线上的 › 圆点跳到目标节点，保留事件原文。\n• 本地化菜单导入 infotexts XML、切换语言；卡片、搜索、试播显示译文。工程内保存词条，XML 导出保留标签。\n• 保存工程：保留 XML 草稿和节点位置；导出 XML：默认保存副本。\n• 本地流程试播需手动选择条件分支，不执行游戏逻辑。\n\nCtrl+O 导入；Ctrl+S 保存工程；Ctrl+Shift+S 导出 XML；F2 编辑节点。文本框中的 Ctrl+Z 撤销输入，工作区 Ctrl+Z 撤销操作。\n\n离线运行，无扫描、遥测、游戏程序集加载或管理员权限要求。",
            "BaroEditor 独立工作台", MessageBoxButton.OK, MessageBoxImage.Information);
    }
}
