using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Barotrauma;
using Microsoft.Xna.Framework;

namespace BaroEditor
{
    internal static class Editor
    {
        private static readonly string Storage = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BaroEditor");
        private static EventDocument document = new(EventDocument.Example);
        private static GUIFrame window;
        private static GUIFrame shell;
        private static DialogView dialog;
        private static bool layoutDirty;
        private static int layoutWidth, layoutHeight;
        private static GUIButton batchButton;
        private static GUITextBlock documentInfo;
        private static readonly Color Background = new(10, 18, 23);
        private static readonly Color Panel = new(19, 32, 39);
        private static readonly Color Card = new(27, 43, 50);
        private static readonly Color Accent = new(109, 177, 158);
        private static readonly Color Foreground = new(221, 231, 230);
        private static readonly Color Muted = new(143, 166, 172);
        private static GUIListBox tree;
        private static GUIListBox inspector;
        private static GUITextBlock status;
        private static GUITextBlock selectedTitle;
        private static GUIButton events;
        private static string treeQuery = "", propertyQuery = "";
        private static EventSearch searchIndex;
        private static long searchRevision = -1, searchDue;
        private static Action pendingSearch;
        private static bool Chinese => T("中", "en") == "中";
        private static string NodeName(string name) => EditorText.DisplayNode(name, Chinese);
        private static string PropertyName(string name) => EditorText.DisplayProperty(name, Chinese);
        private static string selected = "";
        private static string scope = "";
        private static readonly HashSet<string> expanded = new();
        private static readonly Dictionary<string, GUITextBox> attributeBoxes = new();
        private static readonly List<(string Path, GUIButton Button)> treeButtons = new();
        private static GUIButton undoButton, redoButton;
        internal static string T(string zh, string en) => GameSettings.CurrentConfig.Language.ToString().Contains("Chinese", StringComparison.OrdinalIgnoreCase) ? zh : en;
        internal static bool IsOpen => window != null;
        internal static bool DialogOpen => dialog != null;
        private static void ReleaseInput(GUIComponent owner)
        {
            if (owner != null && GUI.KeyboardDispatcher.Subscriber is GUIComponent input && owner.GetAllChildren<GUIComponent>().Contains(input)) GUI.KeyboardDispatcher.Subscriber = null;
        }
        internal static void Close()
        {
            dialog?.Close();
            if (window != null) { ReleaseInput(window); window.RemoveFromGUIUpdateList(true); window.RectTransform.Parent = null; }
            window = null; tree = null; inspector = null; status = null; attributeBoxes.Clear(); treeButtons.Clear();
            pendingSearch = null; searchIndex = null;
        }
        internal static void AddToGUIUpdateList()
        {
            if (window == null) return;
            if (pendingSearch != null && DateTime.UtcNow.Ticks >= searchDue) { var apply = pendingSearch; pendingSearch = null; Try(apply); }
            if (window.Rect.Width != layoutWidth || window.Rect.Height != layoutHeight) layoutDirty = true;
            if (layoutDirty && dialog == null) { CommitAttributes(); BuildLayout(); }
            window.AddToGUIUpdateList();
        }
        private static RectTransform P(int x, int y, int w, int h, RectTransform parent) =>
            new(new Point(Math.Max(1, w), Math.Max(1, h)), parent, Anchor.TopLeft) { AbsoluteOffset = new Point(x, y) };
        private static GUITextBlock Text(RectTransform parent, int x, int y, int w, int h, string text, bool heading = false, Color? color = null) =>
            new(P(x, y, w, h, parent), text, font: heading ? GUIStyle.SubHeadingFont : GUIStyle.SmallFont, wrap: true) { TextColor = color ?? Foreground, CanBeFocused = false };
        private static GUIButton ActionButton(RectTransform parent, int x, int y, int w, int h, string text, Action action, bool primary = false)
        {
            var button = new GUIButton(P(x, y, w, h, parent), text)
            {
                Color = primary ? Accent : Card, HoverColor = primary ? new Color(137, 201, 180) : new Color(43, 65, 73),
                PressedColor = Accent, SelectedColor = Accent, ForceUpperCase = ForceUpperCase.No,
                TextColor = primary ? new Color(12, 32, 31) : Foreground, HoverTextColor = primary ? new Color(12, 32, 31) : Foreground,
                SelectedTextColor = new Color(12, 32, 31)
            };
            button.OnClicked = (_, _) => { Try(action); return true; };
            return button;
        }
        private static GUITextBox Input(RectTransform rect, string initial, bool multiline = false, int limit = 16000)
        {
            int height = rect.Rect.Height;
            var input = new GUITextBox(rect, initial, textAlignment: multiline ? Alignment.TopLeft : Alignment.CenterLeft, wrap: multiline, createPenIcon: false)
                { MaxTextLength = limit, DeselectAfterMessage = !multiline };
            // Vanilla textbox style has a single-line height cap. Keep the actual
            // frame and text region inside our allotted field, including multiline.
            input.RectTransform.MaxSize = new Point(int.MaxValue, int.MaxValue);
            input.RectTransform.MinSize = new Point(0, height);
            input.Frame.RectTransform.MaxSize = new Point(int.MaxValue, int.MaxValue);
            input.Frame.RectTransform.MinSize = new Point(0, height);
            input.Frame.RectTransform.RelativeSize = Vector2.One;
            input.TextBlock.RectTransform.MaxSize = new Point(int.MaxValue, int.MaxValue);
            input.TextBlock.RectTransform.RelativeSize = Vector2.One;
            return input;
        }
        private static void QueueSearch(Action action) { pendingSearch = action; searchDue = DateTime.UtcNow.AddMilliseconds(180).Ticks; }
        private static GUITextBox SearchInput(RectTransform rect, string initial, string hint, Action<string> changed)
        {
            var box = Input(rect, initial, limit: 256); box.ToolTip = hint;
            box.OnTextChangedDelegate = (_, value) => { QueueSearch(() => changed(value)); return true; };
            return box;
        }
        private static RectTransform R(float w, float h, RectTransform parent) => new(new Vector2(w, h), parent);
        private static void Label(RectTransform parent, string text, float height = 0.05f) =>
            new GUITextBlock(R(1, height, parent), text, font: GUIStyle.SmallFont, wrap: true);
        private static GUIButton Button(RectTransform parent, string text, Action action, float width = 1f, float height = .06f)
        {
            var result = new GUIButton(R(width, height, parent), text);
            result.OnClicked = (_, _) => { Try(action); return true; };
            return result;
        }
        private static void Try(Action action)
        {
            try { action(); RefreshHistory(); }
            catch (Exception ex) { Report(ex.Message, true); RefreshTree(); }
        }
        private static void Report(string text, bool error = false)
        {
            if (status != null) { status.Text = text; status.TextColor = error ? Color.OrangeRed : Color.LightYellow; }
            if (error && dialog != null) { dialog.Error.Text = text; dialog.Error.TextColor = Color.OrangeRed; }
            DebugConsole.NewMessage("[BaroEditor] " + text, error ? Color.OrangeRed : Color.LightBlue);
        }
        internal static void Open()
        {
            if (window != null) { CommitAttributes(); return; }
            Close();
            if (scope.Length == 0 && selected.Length == 0) scope = selected = document.EventPaths().FirstOrDefault() ?? "";
            expanded.Add(scope);
            window = new GUIFrame(new RectTransform(Vector2.One, GUI.Canvas), style: null, color: Background);
            BuildLayout();
        }
        private static void BuildLayout()
        {
            layoutDirty = false;
            layoutWidth = window.Rect.Width; layoutHeight = window.Rect.Height;
            window.ClearChildren();
            int w = Math.Min(window.Rect.Width - 40, 1480), h = window.Rect.Height - 32;
            shell = new GUIFrame(P((window.Rect.Width - w) / 2, 16, w, h, window.RectTransform), style: null, color: Background);
            var root = shell.RectTransform;
            Text(root, 8, 4, w - 330, 32, "BaroEditor", true, Accent);
            Text(root, 8, 37, w - 330, 24, T("潜渊症通用事件编辑器", "Barotrauma Universal Event Editor"), color: Muted);
            undoButton = ActionButton(root, w - 276, 15, 84, 34, T("撤销", "Undo"), () => { CommitAttributes(); document.Undo(); ResetSelection(); });
            redoButton = ActionButton(root, w - 182, 15, 84, 34, T("重做", "Redo"), () => { document.Redo(); ResetSelection(); });
            ActionButton(root, w - 88, 15, 80, 34, T("关闭", "Close"), () => { CommitAttributes(); Close(); });
            ActionButton(root, 8, 74, 142, 36, T("导入 XML", "Import XML"), ImportFile);
            ActionButton(root, 160, 74, 162, 36, T("从游戏载入", "Load game event"), ImportGame);
            ActionButton(root, 332, 74, 134, 36, T("新建示例", "New example"), () => ConfirmDiscard(() => SetDocument(new EventDocument(EventDocument.Example))));
            var tools = new GUIDropDown(P(476, 74, 166, 36, root), T("更多工具", "More tools"), elementCount: 3);
            tools.AddItem(T("从原版节点图载入", "Import vanilla graph"), (Action)ImportNative);
            tools.AddItem(T("打开原版节点图", "Open vanilla graph"), (Action)SendToNative);
            tools.AddItem(T("高级：覆盖源文件", "Overwrite local source"), (Action)Overwrite);
            tools.OnSelected = (_, value) => { Try((Action)value); return true; };
            documentInfo = Text(root, 662, 74, Math.Max(1, w - 670), 36, "", color: Muted);
            int bodyY = 126, bodyH = h - 234, leftW = (int)((w - 16) * .34f), rightX = leftW + 16, rightW = w - rightX;
            var left = new GUIFrame(P(0, bodyY, leftW, bodyH, root), style: null, color: Panel);
            Text(left.RectTransform, 16, 10, leftW - 32, 27, T("事件结构", "Event structure"), true);
            events = ActionButton(left.RectTransform, 12, 46, leftW - 24, 34, "", SelectEvent);
            Text(left.RectTransform, 12, 90, 42, 34, T("搜索", "Find"), color: Muted);
            SearchInput(P(58, 90, leftW - 70, 34, left.RectTransform), treeQuery, T("搜索节点、台词、标识符或标签；中英文均可", "Search nodes, dialogue, identifiers or tags in either language"), value => { CommitAttributes(); treeQuery = value; RefreshTree(); });
            tree = new GUIListBox(P(12, 136, leftW - 24, bodyH - 246, left.RectTransform), style: null);
            int third = (leftW - 40) / 3, bottom = bodyH - 96;
            ActionButton(left.RectTransform, 12, bottom, third, 34, T("添加", "Add child"), AddNode);
            ActionButton(left.RectTransform, 20 + third, bottom, third, 34, T("复制", "Duplicate"), () => { CommitAttributes(); document.Duplicate(selected); RefreshEvents(); RefreshTree(); });
            ActionButton(left.RectTransform, 28 + third * 2, bottom, third, 34, T("删除", "Delete"), Delete);
            ActionButton(left.RectTransform, 12, bottom + 44, third, 34, T("上移", "Move up"), () => Move(-1));
            ActionButton(left.RectTransform, 20 + third, bottom + 44, third, 34, T("下移", "Move down"), () => Move(1));
            ActionButton(left.RectTransform, 28 + third * 2, bottom + 44, third, 34, T("折叠", "Collapse"), () => { CommitAttributes(); expanded.Clear(); expanded.Add(scope); RefreshTree(); });
            var right = new GUIFrame(P(rightX, bodyY, rightW, bodyH, root), style: null, color: Panel);
            selectedTitle = Text(right.RectTransform, 20, 12, rightW - 230, 32, "", true, Accent);
            Text(right.RectTransform, 20, 48, rightW - 40, 24, T("编辑当前节点；未填写的属性沿用游戏默认值", "Edit the selected node; omitted properties use game defaults"), color: Muted);
            batchButton = ActionButton(right.RectTransform, rightW - 194, 12, 174, 38, T("批量对话", "Batch dialogue"), BatchDialogue, true);
            Text(right.RectTransform, 16, 84, 64, 34, T("筛选属性", "Filter"), color: Muted);
            SearchInput(P(84, 84, rightW - 100, 34, right.RectTransform), propertyQuery, T("搜索属性中文名、XML 名或当前值", "Search property labels, XML names or values"), value => { CommitAttributes(); propertyQuery = value; RefreshInspector(); });
            inspector = new GUIListBox(P(16, 130, rightW - 32, bodyH - 198, right.RectTransform), style: null);
            int editW = (rightW - 56) / 3;
            ActionButton(right.RectTransform, 16, bodyH - 52, editW, 36, T("应用属性", "Apply attributes"), ApplyAttributes, true);
            ActionButton(right.RectTransform, 28 + editW, bodyH - 52, editW, 36, T("添加属性", "Add attribute"), AddAttribute);
            ActionButton(right.RectTransform, 40 + editW * 2, bodyH - 52, editW, 36, T("编辑 XML", "Edit subtree XML"), EditXml);
            int outY = h - 92;
            var output = new GUIFrame(P(0, outY, w, 58, root), style: null, color: Panel);
            Text(output.RectTransform, 16, 12, 100, 34, T("文件输出", "Output"), true);
            ActionButton(output.RectTransform, 124, 11, 194, 36, T("导出新文件", "Export new file"), Export, true);
            ActionButton(output.RectTransform, 330, 11, 178, 36, T("复制事件 XML", "Copy event XML"), () => Copy(false));
            ActionButton(output.RectTransform, 520, 11, 178, 36, T("复制完整 XML", "Copy full XML"), () => Copy(true));
            Text(output.RectTransform, 722, 8, Math.Max(1, w - 738), 42, T("默认保存副本，原文件保留", "Export saves a copy by default"), color: Muted);
            status = Text(root, 8, h - 25, w - 16, 25, T("就绪 · 选择节点开始编辑", "Ready · select a node to edit"), color: Muted);
            RefreshEvents(); RefreshTree(); RefreshHistory();
        }
        private static void SetDocument(EventDocument next) { document = next; searchIndex = null; scope = selected = ""; expanded.Clear(); expanded.Add(""); RefreshEvents(); RefreshTree(); Report(T("已载入。原文件保留，默认导出副本。", "Loaded. Source retained; export creates a copy by default.")); }
        private static void ResetSelection() { try { document.Element(selected); } catch { selected = scope; } RefreshEvents(); RefreshTree(); }
        private static void RefreshEvents()
        {
            try { document.Element(scope); } catch { scope = ""; }
            events.Text = scope.Length == 0 ? T("整份文件 · 点击选择事件", "Full file · choose event") : EventDocument.Attribute(document.Element(scope), "identifier") + " / " + NodeName(document.Element(scope).Name.LocalName);
        }
        private static void SelectEvent()
        {
            CommitAttributes();
            var choices = new List<PickItem> { new(T("整份文件", "Full file"), "full file 整份文件", "") };
            foreach (var entry in document.EventEntries()) { var node = entry.Node; string id = EventDocument.Attribute(node, "identifier"); choices.Add(new(id + " / " + NodeName(node.Name.LocalName), id + " " + node.Name.LocalName + " " + EditorText.Node(node.Name.LocalName), entry.Path)); }
            Pick(T("选择文件中的事件", "Choose an event in this file"), choices, value => { scope = selected = (string)value; expanded.Add(scope); RefreshEvents(); RefreshTree(); });
        }
        private static void RefreshTree()
        {
            if (tree == null) return;
            try { document.Element(scope); } catch { scope = ""; }
            try { document.Element(selected); } catch { selected = scope; }
            tree.Content.ClearChildren(); treeButtons.Clear();
            HashSet<string> matches = null;
            if (!string.IsNullOrWhiteSpace(treeQuery))
            {
                if (searchIndex == null || searchRevision != document.Revision) { searchIndex = new EventSearch(document.Xml.Root); searchRevision = document.Revision; }
                matches = searchIndex.Find(treeQuery, scope, out int count, out bool limited);
                Report(T($"搜索：{count}{(limited ? "+" : "")} 个匹配；保留父级上下文", $"Search: {count}{(limited ? "+" : "")} matches; ancestor context retained"));
            }
            var stack = new Stack<(XElement Node, string Path, int Depth)>();
            stack.Push((document.Element(scope), scope, 0));
            int visible = 0;
            while (stack.Count > 0 && visible < 1200)
            {
                var entry = stack.Pop();
                if (matches != null && !matches.Contains(entry.Path)) continue;
                visible++;
                string id = EventDocument.Attribute(entry.Node, "identifier");
                string text = EventDocument.Attribute(entry.Node, "text");
                string summary = id.Length > 0 ? id : text;
                if (summary.Length > 35) summary = summary[..35] + "…";
                string path = entry.Path;
                var row = new GUIButton(new RectTransform(new Vector2(1, 0), tree.Content.RectTransform) { MinSize = new Point(0, 60) }, "", style: null)
                {
                    Color = Card, HoverColor = new Color(38, 61, 67), SelectedColor = new Color(40, 75, 73), PressedColor = new Color(40, 75, 73)
                };
                row.RectTransform.MaxSize = new Point(int.MaxValue, int.MaxValue);
                row.RectTransform.MinSize = new Point(0, 60);
                int indent = 10 + Math.Min(entry.Depth, 10) * GUI.IntScale(12);
                int availableWidth = Math.Max(40, row.Rect.Width - indent - 44);
                Text(row.RectTransform, indent + 26, 7, availableWidth, 22, Chinese ? EditorText.Node(entry.Node.Name.LocalName) : entry.Node.Name.LocalName, color: entry.Node.Name.LocalName.Equals("ConversationAction", StringComparison.OrdinalIgnoreCase) ? Accent : Foreground);
                Text(row.RectTransform, indent + 26, 30, availableWidth, 20, summary.Length > 0 ? summary : T("节点", "Node"), color: Muted);
                if (entry.Node.HasElements)
                    ActionButton(row.RectTransform, indent, 12, 22, 28, expanded.Contains(path) ? "-" : "+", () => { CommitAttributes(); selected = path; if (!expanded.Add(path)) expanded.Remove(path); RefreshTree(); });
                row.ToolTip = NodeName(entry.Node.Name.LocalName) + (text.Length > 0 ? "\n" + text : "");
                row.OnClicked = (_, _) => { Try(() => { CommitAttributes(); selected = path; RefreshInspector(); }); return true; };
                treeButtons.Add((path, row));
                if (matches != null || expanded.Contains(path))
                {
                    XElement[] children = entry.Node.Elements().ToArray();
                    for (int i = children.Length - 1; i >= 0; i--) { string childPath = path.Length == 0 ? i.ToString() : path + "/" + i; if (matches == null || matches.Contains(childPath)) stack.Push((children[i], childPath, entry.Depth + 1)); }
                }
            }
            if (stack.Count > 0) Report(T("可见节点达到 1200 个；请折叠分支或选择单个事件。", "1,200 visible nodes reached; collapse branches or select one event."), true);
            RefreshInspector();
        }
        private static void RefreshInspector()
        {
            XElement node = document.Element(selected);
            selectedTitle.Text = Chinese ? EditorText.Node(node.Name.LocalName) : node.Name.LocalName;
            selectedTitle.ToolTip = node.Name.LocalName + " / " + selected;
            batchButton.Enabled = node.Name.LocalName.Equals("ConversationAction", StringComparison.OrdinalIgnoreCase);
            batchButton.ToolTip = batchButton.Enabled ? T("每行一句，保留已有选项和动作", "One message per line; existing options and effects retained") : T("选择对话节点（ConversationAction）后可用", "Select a ConversationAction to enable");
            inspector.Content.ClearChildren(); attributeBoxes.Clear();
            foreach (XAttribute attribute in node.Attributes().Where(a => !a.IsNamespaceDeclaration))
            {
                if (!EditorText.Matches(attribute.Name.LocalName + " " + EditorText.Property(attribute.Name.LocalName) + " " + attribute.Value, propertyQuery)) continue;
                PropertyHint hint = ActionCatalog.Properties(node.Name.LocalName).FirstOrDefault(p => p.Name.Equals(attribute.Name.LocalName, StringComparison.OrdinalIgnoreCase));
                bool longValue = attribute.Value.Length > 16000;
                int height = attribute.Value.Length > 80 ? 124 : 88;
                var row = new GUIFrame(new RectTransform(new Vector2(1, 0), inspector.Content.RectTransform) { MinSize = new Point(0, height) }, style: null, color: Card);
                Text(row.RectTransform, 14, 8, row.Rect.Width - 160, 22, PropertyName(attribute.Name.LocalName));
                Text(row.RectTransform, row.Rect.Width - 144, 8, 130, 22, hint?.Type.Name ?? "XML", color: Muted);
                var box = Input(P(12, 36, row.Rect.Width - 24, height - 48, row.RectTransform), longValue ? attribute.Value[..16000] : attribute.Value, true);
                box.Readonly = longValue;
                if (!longValue) attributeBoxes[attribute.Name.ToString()] = box;
                else box.ToolTip = T("长属性仅显示预览；使用子树 XML 编辑完整内容", "Long value preview; edit the full value in subtree XML");
                if (hint != null && !longValue) box.ToolTip = hint.Type.Name + " / " + T("原版属性", "Vanilla property");
            }
            var note = new GUITextBlock(new RectTransform(new Vector2(1, 0), inspector.Content.RectTransform) { MinSize = new Point(0, GUI.IntScale(68)) },
                ActionCatalog.Actions.ContainsKey(node.Name.LocalName) ? T("原版动作。未填写的属性沿用游戏默认值。", "Vanilla Action. Omitted properties retain game defaults.") :
                T("XML 容器或扩展节点；属性、子节点与原文均保留。", "XML container or extension node; attributes, children and source are retained."), font: GUIStyle.SmallFont, wrap: true);
            foreach (var row in treeButtons) row.Button.Selected = row.Path == selected;
        }
        private static void RefreshHistory()
        {
            if (undoButton != null) { undoButton.Enabled = document.CanUndo; redoButton.Enabled = document.CanRedo; }
            if (documentInfo != null) documentInfo.Text = T(document.Dirty ? "草稿有修改 · 尚未导出" : "草稿已就绪 · 原生 XML", document.Dirty ? "Edited draft · not exported" : "Draft ready · native XML");
        }
        private static void CommitAttributes()
        {
            var changed = attributeBoxes.Where(p => p.Value.Text != document.Element(selected).Attribute(XName.Get(p.Key))?.Value).ToDictionary(p => p.Key, p => p.Value.Text);
            if (changed.Count > 0) document.SetAttributes(selected, changed);
        }
        private static void ApplyAttributes() { CommitAttributes(); RefreshTree(); Report(T("属性已应用。", "Attributes applied.")); }
        private sealed class DialogView
        {
            internal GUIFrame Overlay, Content;
            internal GUITextBlock Error;
            internal GUIButton[] Buttons;
            internal void Close()
            {
                ReleaseInput(Overlay);
                Overlay.RemoveFromGUIUpdateList(true); Overlay.RectTransform.Parent = null;
                if (ReferenceEquals(dialog, this)) { dialog = null; pendingSearch = null; }
            }
        }
        private static DialogView ShowDialog(string title, string message, LocalizedString[] buttons, Vector2? relativeSize = null, Point? minSize = null)
        {
            // All editor dialogs belong to this root. Replacing one cannot close a newer dialog.
            dialog?.Close();
            var view = new DialogView();
            view.Overlay = new GUIFrame(new RectTransform(Vector2.One, window.RectTransform), style: null, color: Color.Black * .78f);
            int w = Math.Min(window.Rect.Width - 48, Math.Max(minSize?.X ?? 500, (int)(window.Rect.Width * (relativeSize?.X ?? .65f))));
            int h = Math.Min(window.Rect.Height - 48, Math.Max(minSize?.Y ?? 280, (int)(window.Rect.Height * (relativeSize?.Y ?? .45f))));
            var frame = new GUIFrame(P((window.Rect.Width - w) / 2, (window.Rect.Height - h) / 2, w, h, view.Overlay.RectTransform), style: null, color: Panel);
            Text(frame.RectTransform, 24, 16, w - 48, 48, title, true, Accent);
            int messageH = message.Length > 0 ? Math.Min(100, Math.Max(54, h / 4)) : 0;
            if (messageH > 0) Text(frame.RectTransform, 24, 72, w - 48, messageH, message);
            view.Content = new GUIFrame(P(24, 76 + messageH, w - 48, h - 160 - messageH, frame.RectTransform), style: null, color: Panel);
            view.Error = Text(frame.RectTransform, 24, h - 80, w - 48, 30, "", color: Muted);
            int buttonW = (w - 48 - (buttons.Length - 1) * 12) / buttons.Length;
            view.Buttons = buttons.Select((caption, index) => ActionButton(frame.RectTransform, 24 + index * (buttonW + 12), h - 44, buttonW, 32, caption.Value, () => view.Close(), index == buttons.Length - 1)).ToArray();
            dialog = view;
            return view;
        }
        private sealed class PickItem
        {
            internal readonly string Caption, Search;
            internal readonly object Value;
            internal PickItem(string caption, string search, object value) { Caption = caption; Search = search; Value = value; }
        }
        private static void Pick(string title, IEnumerable<PickItem> options, Action<object> apply)
        {
            var choices = options.ToArray();
            var box = ShowDialog(title, "", new LocalizedString[] { T("取消", "Cancel"), T("选择", "Select") }, relativeSize: new Vector2(.7f, .78f));
            var body = box.Content.RectTransform;
            Text(body, 0, 0, 50, 34, T("搜索", "Find"), color: Muted);
            var list = new GUIListBox(P(0, 50, box.Content.Rect.Width, box.Content.Rect.Height - 80, body), style: null);
            var count = Text(body, 0, box.Content.Rect.Height - 26, box.Content.Rect.Width, 26, "", color: Muted);
            PickItem selectedItem = null;
            var rows = new List<(PickItem Item, GUIButton Button)>();
            void Filter(string query)
            {
                if (!ReferenceEquals(dialog, box)) return;
                var filtered = choices.Where(item => EditorText.Matches(item.Search + " " + item.Caption, query)).ToArray();
                var shown = filtered.Take(100).ToArray();
                if (!shown.Contains(selectedItem)) selectedItem = shown.FirstOrDefault();
                list.Content.ClearChildren(); rows.Clear();
                foreach (var item in shown)
                {
                    var button = new GUIButton(new RectTransform(new Vector2(1, 0), list.Content.RectTransform) { MinSize = new Point(0, 40) }, item.Caption)
                        { ForceUpperCase = ForceUpperCase.No, Color = Card, TextColor = Foreground, SelectedColor = new Color(40, 75, 73), SelectedTextColor = Foreground };
                    button.ToolTip = item.Caption;
                    button.OnClicked = (_, _) => { selectedItem = item; foreach (var row in rows) row.Button.Selected = ReferenceEquals(row.Item, item); return true; };
                    rows.Add((item, button)); button.Selected = ReferenceEquals(item, selectedItem);
                }
                box.Buttons[1].Enabled = selectedItem != null;
                count.Text = T($"{filtered.Length} 个结果{(filtered.Length > 100 ? " · 仅显示前 100 个，请细化搜索" : "")}", $"{filtered.Length} results{(filtered.Length > 100 ? " · first 100 shown; refine search" : "")}");
            }
            var search = SearchInput(P(54, 0, box.Content.Rect.Width - 54, 34, body), "", T("中文、XML 名称或标识符；空格分隔多个关键词", "Chinese, XML names or identifiers; separate keywords with spaces"), Filter);
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { if (selectedItem == null) return; var item = selectedItem; box.Close(); apply(item.Value); }); return true; };
            Filter(""); search.Select();
        }
        private static void Prompt(string title, string initial, Action<string> apply, bool multiline = false)
        {
            var box = ShowDialog(title, "", new LocalizedString[] { T("取消", "Cancel"), T("应用", "Apply") }, relativeSize: new Vector2(.7f, multiline ? .76f : .38f), minSize: new Point(520, multiline ? 430 : 280));
            var input = Input(multiline ? R(1, .96f, box.Content.RectTransform) : P(0, 8, box.Content.Rect.Width, 44, box.Content.RectTransform), initial, multiline, multiline ? EventDocument.MaxBytes : 32768);
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { apply(input.Text); box.Close(); }); return true; };
            input.Select();
        }
        private static void Confirm(string title, string message, Action action)
        {
            var box = ShowDialog(title, message, new LocalizedString[] { T("取消", "Cancel"), T("继续", "Continue") });
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { action(); box.Close(); }); return true; };
        }
        private static void ConfirmDiscard(Action action)
        {
            if (document.Dirty || attributeBoxes.Any(p => p.Value.Text != document.Element(selected).Attribute(XName.Get(p.Key))?.Value)) Confirm(T("尚有未导出的修改", "Unexported changes"), T("载入其他内容会放弃当前草稿。", "Loading another document discards the current draft."), action);
            else action();
        }
        private static void ImportFile() => Prompt(T("导入 XML / 输入你要读取的文件路径", "Import XML / enter the file path"), Path.Combine(Storage, "Exports"), path =>
            ConfirmDiscard(() => SetDocument(EventDocument.Read(path.Trim().Trim('"')))));
        private static void ImportGame()
        {
            var available = EventSet.GetAllEventPrefabs().Where(e => typeof(ScriptedEvent).IsAssignableFrom(e.EventType)).OrderBy(e => e.Identifier.Value).ToArray();
            if (available.Length == 0) throw new InvalidOperationException("No loaded scripted events found.");
            Pick(T("载入游戏中已加载的事件", "Load a game event"), available.Select(prefab => new PickItem(prefab.Identifier.Value, prefab.Identifier.Value, prefab)), value => ConfirmDiscard(() => SetDocument(new EventDocument(((EventPrefab)value).ConfigElement.Element.ToString(SaveOptions.DisableFormatting)))));
        }
        private static void ImportNative()
        {
            XElement native = GameMain.EventEditorScreen.ExportXML();
            if (native == null) throw new InvalidDataException("The vanilla graph could not export a valid event.");
            ConfirmDiscard(() => SetDocument(new EventDocument(native.ToString(SaveOptions.DisableFormatting))));
        }
        private static void AddNode()
        {
            CommitAttributes();
            var names = new[] { "Option", "Success", "Failure", "Interrupt", "StatusEffect", "Conditional", "Text", "ScriptedEvent", "EventSet" }.Concat(ActionCatalog.Actions.Keys).Distinct().OrderBy(s => s);
            Pick(T("添加子节点 / 搜索原版动作与分支", "Add child / search Actions and branches"), names.Select(name => new PickItem(NodeName(name), name + " " + EditorText.Node(name), name)), value => { document.AddChild(selected, (string)value); expanded.Add(selected); RefreshEvents(); RefreshTree(); });
        }
        private static void AddAttribute()
        {
            CommitAttributes();
            var box = ShowDialog(T("添加或删除属性", "Add or remove an attribute"), "", new LocalizedString[] { T("取消", "Cancel"), T("添加 / 更新", "Add / update"), T("删除属性", "Remove attribute") }, relativeSize: new Vector2(.62f, .6f));
            var layout = new GUILayoutGroup(R(1, .85f, box.Content.RectTransform)) { RelativeSpacing = .02f };
            var search = SearchInput(R(1, .16f, layout.RectTransform), "", T("搜索原版属性：中英文均可", "Search native properties in either language"), _ => { });
            var hints = new GUIDropDown(R(1, .18f, layout.RectTransform), T("搜索并选择原版属性", "Find a native property"), elementCount: 8);
            Label(layout.RectTransform, T("XML 属性名（保持原文）", "XML attribute name"), .07f);
            var name = Input(R(1, .16f, layout.RectTransform), "");
            var value = Input(R(1, .24f, layout.RectTransform), "", true);
            var candidates = ActionCatalog.Properties(document.Element(selected).Name.LocalName);
            void FilterHints(string query) { if (!ReferenceEquals(dialog, box)) return; hints.ListBox.Content.ClearChildren(); foreach (var hint in candidates.Where(p => EditorText.Matches(p.Name + " " + EditorText.Property(p.Name), query))) hints.AddItem(PropertyName(hint.Name) + " / " + hint.Type.Name, hint); }
            search.OnTextChangedDelegate = (_, query) => { QueueSearch(() => FilterHints(query)); return true; };
            FilterHints("");
            hints.OnSelected = (_, item) => { var hint = (PropertyHint)item; name.Text = hint.Name; value.Text = hint.Default; return true; };
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { document.SetAttributes(selected, new Dictionary<string, string> { [name.Text.Trim()] = value.Text }); RefreshTree(); box.Close(); }); return true; };
            box.Buttons[2].OnClicked = (_, _) => { Try(() => { document.RemoveAttribute(selected, name.Text.Trim()); RefreshTree(); box.Close(); }); return true; };
        }
        private static void EditXml() { CommitAttributes(); Prompt(T("编辑选中子树 / 未识别内容保持原文", "Edit selected subtree / unknown content is retained"), EventDocument.PrettyXml(document.Element(selected)), xml => { document.Replace(selected, xml); RefreshEvents(); RefreshTree(); }, true); }
        private static void BatchDialogue()
        {
            CommitAttributes();
            var lines = document.ConversationLines(selected);
            Prompt(T("批量对话 / 每行一句，保留现有选项与动作", "Batch dialogue / one line per message; existing options and actions retained"), string.Join("\n", lines), text =>
            {
                document.SetConversationLines(selected, text.Replace("\r", "").Split('\n').Where(s => s.Trim().Length > 0).ToArray());
                expanded.Add(selected); RefreshTree();
            }, true);
        }
        private static void Move(int delta)
        {
            CommitAttributes();
            string[] parts = selected.Split('/');
            if (selected.Length == 0) return;
            int current = int.Parse(parts[^1]);
            XElement node = document.Element(selected);
            if (delta < 0 && !node.ElementsBeforeSelf().Any() || delta > 0 && !node.ElementsAfterSelf().Any()) return;
            document.Move(selected, delta); parts[^1] = (current + delta).ToString(); selected = string.Join("/", parts); RefreshEvents(); RefreshTree();
        }
        private static void Delete() { CommitAttributes(); Confirm(T("删除选中段落", "Delete selected subtree"), document.Element(selected).Name.LocalName + T(" 及其所有子节点将从草稿删除，可撤销。", " and its children will be removed from the draft; undo is available."), () => { document.Delete(selected); selected = selected.Contains('/') ? selected[..selected.LastIndexOf('/')] : ""; RefreshEvents(); RefreshTree(); }); }
        private static XElement CurrentEvent()
        {
            XElement node = document.Element(selected);
            return node.AncestorsAndSelf().FirstOrDefault(e => e.Name.LocalName.Equals("ScriptedEvent", StringComparison.OrdinalIgnoreCase) || e.Name.LocalName.Equals("TraitorEvent", StringComparison.OrdinalIgnoreCase));
        }
        private static void SendToNative()
        {
            ApplyAttributes();
            XElement current = CurrentEvent();
            if (current == null) throw new InvalidOperationException(T("请在树中选择一个事件或其中的 Action。", "Select an event or one of its Actions in the tree."));
            var unknown = current.Descendants().Where(e => e.Name.LocalName.EndsWith("Action", StringComparison.OrdinalIgnoreCase) && !ActionCatalog.Actions.ContainsKey(e.Name.LocalName)).Select(e => e.Name.LocalName).Distinct().ToArray();
            if (unknown.Length > 0) throw new InvalidOperationException("Vanilla graph cannot represent: " + string.Join(", ", unknown) + ". Use the XML tree to preserve these nodes.");
            EventPrefab prefab = EventPrefab.Create(new ContentXElement(null, new XElement(current)), null, default);
            if (prefab == null) throw new InvalidDataException("The game rejected the event prefab.");
            Confirm(T("打开原版节点图", "Open vanilla node graph"), T("当前 XML 草稿会保留。原版节点图重新导出的 XML 可能省略注释、扩展内容或格式；从节点图载入时会替换当前草稿。", "The XML draft is retained. The vanilla graph exporter may omit comments, extensions or formatting; loading from the graph replaces the draft."), () => { GameMain.EventEditorScreen.Load(prefab); Close(); });
        }
        private static void Export()
        {
            ApplyAttributes();
            string initial = document.SourcePath == null ? "BaroEditor-event.xml" : Path.GetFileName(document.SourcePath);
            Prompt(T("导出整份 XML 副本 / 文件名", "Export the full XML copy / file name"), initial, name =>
                Report(document.SaveCopy(Path.Combine(Storage, "Exports"), name.Trim())));
        }
        private static void Copy(bool full)
        {
            ApplyAttributes();
            XElement current = CurrentEvent();
            if (!full && current == null) throw new InvalidOperationException("Select an event first.");
            Clipboard.SetText(EventDocument.PrettyXml(full ? (XNode)document.Xml : current));
            Report(T("XML 已复制到剪贴板。", "XML copied to clipboard."));
        }
        private static void Overwrite()
        {
            ApplyAttributes();
            if (document.SourcePath == null) throw new InvalidOperationException(T("游戏内载入的事件没有可覆盖的源文件，请导出副本。", "Events loaded from game memory have no writable source; export a copy."));
            string game = Path.GetFullPath(Directory.GetCurrentDirectory());
            foreach (string protectedFolder in new[] { "Content", "DLC" })
                if (document.SourcePath.StartsWith(Path.Combine(game, protectedFolder) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                    throw new IOException(T("原版资源目录保持只读，请导出副本。", "Vanilla resource directories are read-only in this tool. Export a copy."));
            if (document.SourcePath.Replace('\\', '/').Contains("/workshop/content/", StringComparison.OrdinalIgnoreCase))
                throw new IOException(T("工坊缓存保持只读，请先复制到本地模组项目。", "Workshop caches are read-only; copy to a local mod project first."));
            Confirm(T("覆盖你导入的本地源文件", "Overwrite the imported local source"), document.SourcePath + "\n" + T("先备份，原文件被外部修改时停止。", "A backup is made first; external changes abort the overwrite."), () => { document.OverwriteSource(Path.Combine(Storage, "Backups")); Report(T("源文件已更新，备份保存在 BaroEditor/Backups。", "Source updated; backup saved in BaroEditor/Backups.")); });
        }
    }
}
