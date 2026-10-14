using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Xml.Linq;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private Window activeDialog;
        private void RefreshInspector()
        {
            if (properties == null) return;
            bool previous = building; building = true;
            try
            {
                fields.Clear(); properties.Children.Clear(); var node = Model.Current;
                inspectorTitle.Text = EditorText.Node(node.Name.LocalName); inspectorTitle.ToolTip = node.Name.LocalName + " · " + Model.Selected;
                var specs = catalog.Properties(node.Name.LocalName);
                var actual = node.Attributes().Where(a => !a.IsNamespaceDeclaration).Select(a => a.Name.ToString());
                var keys = actual.Concat(specs.Select(p => p.Name).Where(name => !node.Attributes().Any(a => a.Name.LocalName.Equals(name, StringComparison.OrdinalIgnoreCase)))).Distinct().ToArray();
                int visible = 0;
                foreach (string key in keys)
                {
                    var attribute = node.Attribute(XName.Get(key)); string local = XName.Get(key).LocalName;
                    var hint = specs.FirstOrDefault(p => p.Name.Equals(local, StringComparison.OrdinalIgnoreCase));
                    if (!EditorText.Matches(local + " " + EditorText.Property(local) + " " + attribute?.Value, propertySearch.Text)) continue;
                    if (++visible > 100) { properties.Children.Add(Text("仅显示前 100 个属性，请细化搜索。", 12, amber)); break; }
                    var body = new StackPanel(); var top = new DockPanel();
                    var enabled = new CheckBox { IsChecked = attribute != null, Content = attribute != null ? "已设置" : "启用", Foreground = muted, FontSize = 11, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0), ToolTip = "未启用的属性不写入 XML；沿用游戏默认值" }; DockPanel.SetDock(enabled, Dock.Right); top.Children.Add(enabled);
                    var names = new StackPanel(); names.Children.Add(Text(EditorText.Property(local), 12, ink, true)); var raw = Text(key + (hint != null ? " · " + hint.Type : " · XML"), 10, muted); raw.TextTrimming = TextTrimming.CharacterEllipsis; raw.TextWrapping = TextWrapping.NoWrap; names.Children.Add(raw); top.Children.Add(names); body.Children.Add(top);
                    var input = new TextBox { Text = attribute?.Value ?? hint?.Default ?? "", IsEnabled = attribute != null, MaxLength = EventDocument.MaxBytes, AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 8, 0, 0), MinHeight = local is "text" or "message" || (attribute?.Value.Length ?? 0) > 80 ? 84 : 36, MaxHeight = 150, ToolTip = hint == null ? "扩展属性，保持原值" : "原版属性 · 默认：" + hint.Default + (hint.Choices.Length > 0 ? "\n可选值：" + string.Join(", ", hint.Choices) : "") };
                    body.Children.Add(input);
                    enabled.Checked += (_, _) => { input.IsEnabled = true; enabled.Content = "已设置"; }; enabled.Unchecked += (_, _) => { input.IsEnabled = false; enabled.Content = "启用"; };
                    if (hint != null && (hint.Type == "Boolean" || hint.Choices.Length > 0))
                    {
                        var choose = Btn("选择值 ▾", () =>
                        {
                            var menu = new ContextMenu { Background = panel, Foreground = ink };
                            foreach (string value in hint.Type == "Boolean" ? new[] { "true", "false" } : hint.Choices)
                            { var item = new MenuItem { Header = value }; item.Click += (_, _) => { enabled.IsChecked = true; input.Text = value; }; menu.Items.Add(item); }
                            menu.PlacementTarget = input; menu.IsOpen = true;
                        }); choose.FontSize = 10; choose.Padding = new Thickness(6, 3, 6, 3); choose.HorizontalAlignment = HorizontalAlignment.Right; choose.Margin = new Thickness(0, 4, 0, 0); body.Children.Add(choose);
                    }
                    var card = Box(body, new Thickness(10)); card.Background = bg; card.Margin = new Thickness(0, 0, 0, 10); properties.Children.Add(card); fields[key] = (enabled, input, attribute != null);
                }
                properties.Children.Add(Text("未启用的属性沿用游戏默认值。\n未知属性和节点会保留，XML 名称保持原文。", 11, muted));
                if (visible == 0) properties.Children.Insert(0, Text("没有匹配的属性", 12, muted));
            }
            finally { building = previous; }
        }
        private void CommitInspector()
        {
            if (building || Model == null || fields.Count == 0) return;
            var node = Model.Current; var changed = new Dictionary<string, string>();
            foreach (var entry in fields)
            {
                string value = entry.Value.Enabled.IsChecked == true ? entry.Value.Value.Text : null;
                if (node.Attribute(XName.Get(entry.Key))?.Value != value) changed[entry.Key] = value;
            }
            if (changed.Count > 0) Model.Change(doc => doc.SetAttributes(Model.Selected, changed));
        }
        private void ApplyInspector() { CommitInspector(); RefreshAll(); SetStatus("属性已应用 · 可撤销"); }
        private void RefreshXml()
        {
            string xml = EventDocument.PrettyXml(Model.Current); xmlPreview.Text = xml.Length > 20000 ? xml[..20000] + "\n…预览截取前 20,000 字符，编辑与复制使用完整内容。" : xml;
        }
        private Window Dialog(string title, double height = 480)
        {
            if (activeDialog != null) { activeDialog.Activate(); throw new InvalidOperationException("请先关闭当前编辑窗口。"); }
            var window = new Window { Title = title, Owner = this, Width = Math.Min(720, ActualWidth - 80), Height = Math.Min(height, ActualHeight - 80), MinWidth = 460, MinHeight = 240, Background = bg, Foreground = ink, FontFamily = FontFamily, FontSize = FontSize, WindowStartupLocation = WindowStartupLocation.CenterOwner, ResizeMode = ResizeMode.CanResize };
            window.Resources.MergedDictionaries.Add(Resources); activeDialog = window;
            window.Closed += (_, _) => { activeDialog = null; if (delays.TryGetValue("dialog", out var timer)) { timer.Stop(); delays.Remove("dialog"); } }; return window;
        }
        private void TextDialog(string title, string initial, Action<string> apply, bool multiline = true, string help = null)
        {
            var dialog = Dialog(title, multiline ? 560 : 300); var body = Rows(GridLength.Auto, new GridLength(1, GridUnitType.Star), GridLength.Auto, GridLength.Auto); body.Margin = new Thickness(18); dialog.Content = body;
            At(body, Text(help ?? "修改将在点击“应用”后写入当前草稿。", 12, muted));
            var input = new TextBox { Text = initial, AcceptsReturn = multiline, AcceptsTab = multiline, TextWrapping = multiline ? TextWrapping.Wrap : TextWrapping.NoWrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, Margin = new Thickness(0, 14, 0, 12), MaxLength = EventDocument.MaxBytes }; At(body, input, 1);
            var error = Text("", 12, amber); At(body, error, 2); var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) }; buttons.Children.Add(Btn("取消", dialog.Close));
            var accept = Btn("应用", () => { try { apply(input.Text); dialog.Close(); } catch (Exception e) { error.Text = e.Message; } }, true); buttons.Children.Add(accept); At(body, buttons, 3); dialog.Loaded += (_, _) => { input.Focus(); if (!multiline) input.SelectAll(); }; dialog.ShowDialog();
        }
        private void EditNode()
        {
            CommitInspector(); var node = Model.Current;
            if (node.Name.LocalName is "ConversationAction" or "Option" or "ForceSayAction" or "MessageBoxAction" || node.Attribute("text") != null)
            {
                string key = node.Attributes().FirstOrDefault(a => a.Name.LocalName.Equals("text", StringComparison.OrdinalIgnoreCase))?.Name.ToString() ?? "text";
                TextDialog("编辑 " + EditorText.Node(node.Name.LocalName) + " 文本", node.Attribute(XName.Get(key))?.Value ?? "", text => { Model.Change(doc => doc.SetAttributes(Model.Selected, new Dictionary<string, string> { [key] = text })); RefreshAll(); });
            }
            else EditXml();
        }
        private void EditXml()
        {
            CommitInspector(); TextDialog("编辑选中子树 XML", EventDocument.PrettyXml(Model.Current), xml => { Model.Change(doc => doc.Replace(Model.Selected, xml)); RefreshAll(); }, true, "完整子树编辑 · XML 标签保持原名；未知节点、注释与属性保留。删除原文会删除对应内容。");
        }
        private void BatchDialogue()
        {
            CommitInspector(); if (Model.Current.Name.LocalName != "ConversationAction") throw new InvalidOperationException("请先选择对话节点。");
            var lines = Model.Document.ConversationLines(Model.Selected);
            TextDialog("批量对话 · 每行一句", string.Join("\n", lines), text => { var values = text.Replace("\r", "").Split('\n').Where(s => s.Trim().Length > 0).ToArray(); Model.Change(doc => doc.SetConversationLines(Model.Selected, values)); RefreshAll(); }, true, "保留已有选项、分支和动作。复杂 Text 替换使用 XML 编辑；缩短已有链须明确删除节点。");
        }
        private void AddCustomNode()
        {
            TextDialog("自定义 XML 节点", "CustomAction", name => { System.Xml.XmlConvert.VerifyNCName(name.Trim()); AddAction(name.Trim(), Model.Selected); }, false);
        }
        private void AddAttribute()
        {
            CommitInspector(); var dialog = Dialog("添加属性 · 原版提示与自定义名称", 600); var root = Rows(GridLength.Auto, new GridLength(1, GridUnitType.Star), GridLength.Auto, GridLength.Auto, GridLength.Auto, GridLength.Auto, GridLength.Auto); root.Margin = new Thickness(18); dialog.Content = root;
            var list = new ListBox { Background = panel, Foreground = ink, BorderBrush = line, MaxHeight = 180, DisplayMemberPath = "Label" };
            var available = catalog.Properties(Model.Current.Name.LocalName); var name = new TextBox { Margin = new Thickness(0, 6, 0, 10) }; var value = new TextBox { AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 70, MaxHeight = 120, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            void Filter(string query) { list.ItemsSource = available.Where(p => EditorText.Matches(p.Name + " " + EditorText.Property(p.Name), query)).Select(p => new PropertyChoice { Label = EditorText.DisplayProperty(p.Name, true), Spec = p }).ToArray(); }
            var search = Search("搜索原版属性中文名或 XML 名", Filter, "dialog"); At(root, search); At(root, list, 1); At(root, Text("XML 属性名", 12, muted), 2); At(root, name, 3); At(root, Text("属性值（可留空）", 12, muted), 4); At(root, value, 5);
            list.SelectionChanged += (_, _) => { if (list.SelectedItem is PropertyChoice choice) { name.Text = choice.Spec.Name; value.Text = choice.Spec.Default; } };
            var buttons = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right, Margin = new Thickness(0, 12, 0, 0) }; buttons.Children.Add(Btn("取消", dialog.Close)); buttons.Children.Add(Btn("添加 / 更新", () => { try { var key = XName.Get(name.Text.Trim()).ToString(); Model.Change(doc => doc.SetAttributes(Model.Selected, new Dictionary<string, string> { [key] = value.Text })); RefreshAll(); dialog.Close(); } catch (Exception e) { MessageBox.Show(dialog, e.Message, "属性无效"); } }, true)); At(root, buttons, 6); Filter(""); dialog.ShowDialog();
        }
        private sealed class PropertyChoice { public string Label { get; set; } public PropertySpec Spec { get; set; } }
        private void Duplicate()
        {
            CommitInspector(); var node = Model.Current; Model.Change(doc => doc.Duplicate(Model.Selected)); Model.Select(Model.Document.PathOf(node.ElementsAfterSelf().First())); Model.FinalizeSelection(); RefreshAll();
        }
        private void DeleteNode()
        {
            CommitInspector(); if (Model.Selected.Length == 0) throw new InvalidOperationException("文件根节点不能删除。");
            if (!Confirm("删除“" + EditorText.Node(Model.Current.Name.LocalName) + "”及其全部子节点？\n可以撤销。")) return;
            bool scopeDeleted = Model.Selected == Model.Scope; Model.Change(doc => doc.Delete(Model.Selected)); if (scopeDeleted) Model.SetScope(Model.Document.EventEntries().FirstOrDefault().Path ?? ""); RefreshAll();
        }
        private void Move(int delta) { CommitInspector(); Model.Change(doc => doc.Move(Model.Selected, delta)); RefreshAll(); }
        private void RefreshPreview()
        {
            playback.Children.Clear(); playback.Children.Add(Text("本地流程试播", 16, accent, true)); playback.Children.Add(Text("手动选择条件分支；不执行游戏效果、脚本或事件。", 11, muted));
            var node = preview.Current;
            if (node == null) playback.Children.Add(Text(preview.Limited ? "已到达 256 步上限" : "流程结束", 19, ink, true));
            else
            {
                var body = new StackPanel(); body.Children.Add(Text(EditorText.Node(node.Name.LocalName), 14, accent, true)); string text = EventDocument.Attribute(node, "text"); body.Children.Add(Text(text.Length > 0 ? text : NodeDescription(node), 16, ink)); body.Children.Add(Text(node.Name.LocalName, 10, muted)); var card = Box(body); card.Margin = new Thickness(0, 18, 0, 16); playback.Children.Add(card);
                foreach (var branch in preview.Choices)
                {
                    string label = EventDocument.Attribute(branch, "text"); var choice = Btn(label.Length > 0 ? label : EditorText.Node(branch.Name.LocalName), () => { preview.Advance(branch); RefreshPreview(); }); choice.Margin = new Thickness(0, 0, 0, 9); playback.Children.Add(choice);
                }
                if (!preview.Choices.Any()) { var next = Btn("继续 →", () => { preview.Advance(); RefreshPreview(); }, true); next.Margin = new Thickness(0, 0, 0, 12); playback.Children.Add(next); }
                var locate = Btn("在画布中定位", () => { SelectNode(Model.Document.PathOf(node)); if (Model.Positions.TryGetValue(node, out var point)) { graphScroll.ScrollToHorizontalOffset(Math.Max(0, point.X * zoom.Value - 60)); graphScroll.ScrollToVerticalOffset(Math.Max(0, point.Y * zoom.Value - 80)); } }); playback.Children.Add(locate);
            }
            var restart = Btn("↶ 从头试播", () => { CommitInspector(); preview.Start(Model.Document.Element(Model.Scope)); RefreshPreview(); }); restart.Margin = new Thickness(0, 16, 0, 14); playback.Children.Add(restart); playback.Children.Add(Text("经过：" + string.Join(" → ", preview.Route.TakeLast(12)), 11, muted));
        }
        private void OnKey(object sender, KeyEventArgs e)
        {
            if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control))
            {
                if (e.Key == Key.S) { Safe(Keyboard.Modifiers.HasFlag(ModifierKeys.Shift) ? ExportXml : SaveProject); e.Handled = true; }
                else if (e.Key == Key.O) { Safe(OpenFile); e.Handled = true; }
                else if (e.Key == Key.Z && Keyboard.FocusedElement is not TextBox) { Safe(() => { CommitInspector(); Model.Undo(); RefreshAll(); }); e.Handled = true; }
                else if (e.Key == Key.Y && Keyboard.FocusedElement is not TextBox) { Safe(() => { Model.Redo(); RefreshAll(); }); e.Handled = true; }
            }
            else if (e.Key == Key.Escape) { linkSource = null; if (ghost != null) ghost.Data = null; SetStatus("连接已取消"); }
            else if (e.Key == Key.F2 && Keyboard.FocusedElement is not TextBox) { Safe(EditNode); e.Handled = true; }
            else if (e.Key == Key.Delete && Keyboard.FocusedElement is not TextBox) { Safe(DeleteNode); e.Handled = true; }
        }
    }
}
