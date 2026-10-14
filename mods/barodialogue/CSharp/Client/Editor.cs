using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using Barotrauma;
using Microsoft.Xna.Framework;

namespace BaroDialogue
{
    internal static class Editor
    {
        private static readonly string Storage = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "BaroDialogue");
        private static EventDocument document = new(EventDocument.Example);
        private static GUIMessageBox window;
        private static GUIListBox tree;
        private static GUIListBox inspector;
        private static GUITextBlock status;
        private static GUITextBlock selectedTitle;
        private static GUIDropDown events;
        private static string selected = "";
        private static string scope = "";
        private static readonly HashSet<string> expanded = new();
        private static readonly Dictionary<string, GUITextBox> attributeBoxes = new();
        private static readonly List<(string Path, GUIButton Button)> treeButtons = new();
        private static GUIButton undoButton, redoButton;
        internal static string T(string zh, string en) => GameSettings.CurrentConfig.Language.ToString().Contains("Chinese", StringComparison.OrdinalIgnoreCase) ? zh : en;
        internal static void Close() { window?.Close(); window = null; }
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
            DebugConsole.NewMessage("[BaroDialogue] " + text, error ? Color.OrangeRed : Color.LightBlue);
        }
        internal static void Open()
        {
            Close();
            if (scope.Length == 0 && selected.Length == 0) scope = selected = document.EventPaths().FirstOrDefault() ?? "";
            expanded.Add(scope);
            window = new GUIMessageBox("BaroDialogue — " + T("原版事件与对话编辑器", "Vanilla Event & Dialogue Editor"), "", new LocalizedString[] { T("关闭", "Close") },
                relativeSize: new Vector2(.94f, .9f), minSize: new Point(780, 580));
            window.Buttons[0].OnClicked = (_, _) => { Try(() => { CommitAttributes(); Close(); }); return true; };
            var layout = new GUILayoutGroup(R(1, .9f, window.Content.RectTransform)) { Stretch = true, RelativeSpacing = .012f };
            var top = new GUILayoutGroup(R(1, .07f, layout.RectTransform), isHorizontal: true) { RelativeSpacing = .012f };
            Button(top.RectTransform, T("导入 XML", "Import XML"), ImportFile, .18f, 1);
            Button(top.RectTransform, T("从游戏载入", "Load game event"), ImportGame, .2f, 1);
            Button(top.RectTransform, T("从节点图载入", "Load node graph"), ImportNative, .22f, 1);
            Button(top.RectTransform, T("新建示例", "New example"), () => ConfirmDiscard(() => SetDocument(new EventDocument(EventDocument.Example))), .18f, 1);
            undoButton = Button(top.RectTransform, T("撤销", "Undo"), () => { CommitAttributes(); document.Undo(); ResetSelection(); }, .09f, 1);
            redoButton = Button(top.RectTransform, T("重做", "Redo"), () => { document.Redo(); ResetSelection(); }, .09f, 1);
            events = new GUIDropDown(R(1, .055f, layout.RectTransform), T("选择事件或整份文件", "Select an event or the full file"), elementCount: 8);
            var body = new GUILayoutGroup(R(1, .69f, layout.RectTransform), isHorizontal: true) { RelativeSpacing = .025f, Stretch = true };
            tree = new GUIListBox(R(.37f, 1, body.RectTransform));
            var right = new GUILayoutGroup(R(.605f, 1, body.RectTransform)) { Stretch = true, RelativeSpacing = .015f };
            selectedTitle = new GUITextBlock(R(1, .06f, right.RectTransform), "", font: GUIStyle.SubHeadingFont);
            inspector = new GUIListBox(R(1, .68f, right.RectTransform));
            var edits = new GUILayoutGroup(R(1, .1f, right.RectTransform), isHorizontal: true) { RelativeSpacing = .02f };
            Button(edits.RectTransform, T("应用属性", "Apply attributes"), ApplyAttributes, .3f, 1);
            Button(edits.RectTransform, T("添加属性", "Add attribute"), AddAttribute, .3f, 1);
            Button(edits.RectTransform, T("编辑此段 XML", "Edit subtree XML"), EditXml, .36f, 1);
            var extra = new GUILayoutGroup(R(1, .1f, right.RectTransform), isHorizontal: true) { RelativeSpacing = .02f };
            Button(extra.RectTransform, T("批量编辑对话", "Batch dialogue"), BatchDialogue, .48f, 1);
            Button(extra.RectTransform, T("原版节点图", "Vanilla node graph"), SendToNative, .48f, 1);
            var change = new GUILayoutGroup(R(1, .065f, layout.RectTransform), isHorizontal: true) { RelativeSpacing = .01f };
            Button(change.RectTransform, T("添加子节点", "Add child"), AddNode, .24f, 1);
            Button(change.RectTransform, T("复制段落", "Duplicate"), () => { CommitAttributes(); document.Duplicate(selected); RefreshEvents(); RefreshTree(); }, .2f, 1);
            Button(change.RectTransform, T("上移", "Move up"), () => Move(-1), .14f, 1);
            Button(change.RectTransform, T("下移", "Move down"), () => Move(1), .14f, 1);
            Button(change.RectTransform, T("删除", "Delete"), Delete, .2f, 1);
            var output = new GUILayoutGroup(R(1, .065f, layout.RectTransform), isHorizontal: true) { RelativeSpacing = .01f };
            Button(output.RectTransform, T("导出新文件", "Export new file"), Export, .24f, 1);
            Button(output.RectTransform, T("复制事件 XML", "Copy event XML"), () => Copy(false), .24f, 1);
            Button(output.RectTransform, T("复制整文件 XML", "Copy full XML"), () => Copy(true), .24f, 1);
            Button(output.RectTransform, T("高级：覆盖源文件", "Advanced: overwrite source"), Overwrite, .24f, 1);
            status = new GUITextBlock(R(1, .06f, layout.RectTransform), T("只在操作时处理 XML；导入内容不会执行。", "XML is processed only on interaction; imported actions are never executed."), font: GUIStyle.SmallFont, wrap: true);
            RefreshEvents(); RefreshTree(); RefreshHistory();
        }
        private static void SetDocument(EventDocument next) { document = next; scope = selected = ""; expanded.Clear(); expanded.Add(""); RefreshEvents(); RefreshTree(); Report(T("已载入。原文件保留，默认导出副本。", "Loaded. Source retained; export creates a copy by default.")); }
        private static void ResetSelection() { scope = selected = ""; expanded.Clear(); expanded.Add(""); RefreshEvents(); RefreshTree(); }
        private static void RefreshEvents()
        {
            events.OnSelected = null;
            try { document.Element(scope); } catch { scope = ""; }
            events.ListBox.Content.ClearChildren();
            events.AddItem(T("整份文件", "Full file"), "");
            foreach (string path in document.EventPaths())
                events.AddItem(EventDocument.Attribute(document.Element(path), "identifier") + " / " + document.Element(path).Name.LocalName, path);
            events.SelectItem(scope);
            events.OnSelected = (_, value) => { Try(() => { CommitAttributes(); scope = selected = (string)value; expanded.Add(scope); RefreshTree(); }); return true; };
        }
        private static void RefreshTree()
        {
            if (tree == null) return;
            try { document.Element(scope); } catch { scope = ""; }
            try { document.Element(selected); } catch { selected = scope; }
            tree.Content.ClearChildren(); treeButtons.Clear();
            var stack = new Stack<(XElement Node, string Path, int Depth)>();
            stack.Push((document.Element(scope), scope, 0));
            int visible = 0;
            while (stack.Count > 0 && visible++ < 1200)
            {
                var entry = stack.Pop();
                string marker = entry.Node.HasElements ? expanded.Contains(entry.Path) ? "▾ " : "▸ " : "  ";
                string id = EventDocument.Attribute(entry.Node, "identifier");
                string text = EventDocument.Attribute(entry.Node, "text");
                string summary = id.Length > 0 ? id : text;
                if (summary.Length > 35) summary = summary[..35] + "…";
                string caption = new string(' ', Math.Min(entry.Depth, 12) * 2) + marker + entry.Node.Name.LocalName + (summary.Length > 0 ? " · " + summary : "");
                string path = entry.Path;
                var row = new GUIButton(new RectTransform(new Vector2(1, 0), tree.Content.RectTransform) { MinSize = new Point(0, GUI.IntScale(31)) }, caption, textAlignment: Alignment.CenterLeft);
                row.ToolTip = entry.Node.Name.LocalName + (text.Length > 0 ? "\n" + text : "");
                row.OnClicked = (_, _) => { Try(() => { CommitAttributes(); selected = path; if (entry.Node.HasElements) { if (!expanded.Add(path)) expanded.Remove(path); RefreshTree(); } else RefreshInspector(); }); return true; };
                treeButtons.Add((path, row));
                if (expanded.Contains(path))
                {
                    XElement[] children = entry.Node.Elements().ToArray();
                    for (int i = children.Length - 1; i >= 0; i--) stack.Push((children[i], path.Length == 0 ? i.ToString() : path + "/" + i, entry.Depth + 1));
                }
            }
            if (stack.Count > 0) Report(T("可见节点达到 1200 个；请折叠分支或选择单个事件。", "1,200 visible nodes reached; collapse branches or select one event."), true);
            RefreshInspector();
        }
        private static void RefreshInspector()
        {
            XElement node = document.Element(selected);
            selectedTitle.Text = node.Name.LocalName;
            inspector.Content.ClearChildren(); attributeBoxes.Clear();
            foreach (XAttribute attribute in node.Attributes().Where(a => !a.IsNamespaceDeclaration))
            {
                var row = new GUILayoutGroup(new RectTransform(new Vector2(1, 0), inspector.Content.RectTransform) { MinSize = new Point(0, GUI.IntScale(64)) });
                Label(row.RectTransform, attribute.Name.LocalName, .35f);
                var box = new GUITextBox(R(1, .6f, row.RectTransform), attribute.Value, wrap: true) { MaxTextLength = 16000 };
                attributeBoxes[attribute.Name.ToString()] = box;
                PropertyHint hint = ActionCatalog.Properties(node.Name.LocalName).FirstOrDefault(p => p.Name.Equals(attribute.Name.LocalName, StringComparison.OrdinalIgnoreCase));
                if (hint != null) box.ToolTip = hint.Type.Name + " / " + T("原版属性", "Vanilla property");
            }
            var note = new GUITextBlock(new RectTransform(new Vector2(1, 0), inspector.Content.RectTransform) { MinSize = new Point(0, GUI.IntScale(68)) },
                ActionCatalog.Actions.ContainsKey(node.Name.LocalName) ? T("原版 Action。未填写的属性沿用游戏默认值。", "Vanilla Action. Omitted properties retain game defaults.") :
                T("XML 容器或扩展节点；属性、子节点与原文均保留。", "XML container or extension node; attributes, children and source are retained."), font: GUIStyle.SmallFont, wrap: true);
            foreach (var row in treeButtons) row.Button.Selected = row.Path == selected;
        }
        private static void RefreshHistory() { if (undoButton != null) { undoButton.Enabled = document.CanUndo; redoButton.Enabled = document.CanRedo; } }
        private static void CommitAttributes()
        {
            var changed = attributeBoxes.Where(p => p.Value.Text != document.Element(selected).Attribute(XName.Get(p.Key))?.Value).ToDictionary(p => p.Key, p => p.Value.Text);
            if (changed.Count > 0) document.SetAttributes(selected, changed);
        }
        private static void ApplyAttributes() { CommitAttributes(); RefreshTree(); Report(T("属性已应用。", "Attributes applied.")); }
        private static void Prompt(string title, string initial, Action<string> apply, bool multiline = false)
        {
            var box = new GUIMessageBox(title, "", new LocalizedString[] { T("取消", "Cancel"), T("应用", "Apply") }, relativeSize: new Vector2(.76f, multiline ? .76f : .35f), minSize: new Point(520, multiline ? 430 : 200));
            var input = new GUITextBox(R(1, .8f, box.Content.RectTransform), initial, textAlignment: Alignment.TopLeft, wrap: multiline) { MaxTextLength = multiline ? EventDocument.MaxBytes : 32768 };
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { apply(input.Text); box.Close(); }); return true; };
            input.Select();
        }
        private static void Confirm(string title, string message, Action action)
        {
            var box = new GUIMessageBox(title, message, new LocalizedString[] { T("取消", "Cancel"), T("继续", "Continue") });
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
            var box = new GUIMessageBox(T("载入游戏中已加载的事件", "Load an event currently loaded by the game"), "", new LocalizedString[] { T("取消", "Cancel"), T("载入", "Load") }, relativeSize: new Vector2(.6f, .3f));
            var list = new GUIDropDown(R(1, .25f, box.Content.RectTransform), elementCount: 12);
            foreach (var prefab in available) list.AddItem(prefab.Identifier.Value, prefab);
            list.SelectItem(available[0]);
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => ConfirmDiscard(() => { var prefab = (EventPrefab)list.SelectedData; SetDocument(new EventDocument(prefab.ConfigElement.Element.ToString(SaveOptions.DisableFormatting))); box.Close(); })); return true; };
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
            var box = new GUIMessageBox(T("添加子节点 / 原版 Action 与分支", "Add child / vanilla Action or branch"), "", new LocalizedString[] { T("取消", "Cancel"), T("添加", "Add") }, relativeSize: new Vector2(.6f, .32f));
            var list = new GUIDropDown(R(1, .27f, box.Content.RectTransform), elementCount: 12);
            foreach (string name in new[] { "Option", "Success", "Failure", "Interrupt", "StatusEffect", "Conditional", "Text", "ScriptedEvent", "EventSet" }.Concat(ActionCatalog.Actions.Keys).Distinct().OrderBy(s => s)) list.AddItem(name, name);
            list.SelectItem("ConversationAction");
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { document.AddChild(selected, (string)list.SelectedData); expanded.Add(selected); RefreshEvents(); RefreshTree(); box.Close(); }); return true; };
        }
        private static void AddAttribute()
        {
            CommitAttributes();
            var box = new GUIMessageBox(T("添加或删除属性", "Add or remove an attribute"), "", new LocalizedString[] { T("取消", "Cancel"), T("添加 / 更新", "Add / update"), T("删除属性", "Remove attribute") }, relativeSize: new Vector2(.62f, .4f));
            var layout = new GUILayoutGroup(R(1, .85f, box.Content.RectTransform)) { RelativeSpacing = .02f };
            var hints = new GUIDropDown(R(1, .2f, layout.RectTransform), T("原版属性提示", "Vanilla property hints"), elementCount: 10);
            var name = new GUITextBox(R(1, .2f, layout.RectTransform), "");
            var value = new GUITextBox(R(1, .24f, layout.RectTransform), "", wrap: true);
            foreach (PropertyHint hint in ActionCatalog.Properties(document.Element(selected).Name.LocalName)) hints.AddItem(hint.Name + " / " + hint.Type.Name, hint);
            hints.OnSelected = (_, item) => { var hint = (PropertyHint)item; name.Text = hint.Name; value.Text = hint.Default; return true; };
            box.Buttons[0].OnClicked = (_, _) => { box.Close(); return true; };
            box.Buttons[1].OnClicked = (_, _) => { Try(() => { document.SetAttributes(selected, new Dictionary<string, string> { [name.Text.Trim()] = value.Text }); RefreshTree(); box.Close(); }); return true; };
            box.Buttons[2].OnClicked = (_, _) => { Try(() => { document.RemoveAttribute(selected, name.Text.Trim()); RefreshTree(); box.Close(); }); return true; };
        }
        private static void EditXml() { CommitAttributes(); Prompt(T("编辑选中子树 / 未识别内容保持原文", "Edit selected subtree / unknown content is retained"), document.Element(selected).ToString(SaveOptions.DisableFormatting), xml => { document.Replace(selected, xml); RefreshEvents(); RefreshTree(); }, true); }
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
            string initial = document.SourcePath == null ? "BaroDialogue-event.xml" : Path.GetFileName(document.SourcePath);
            Prompt(T("导出整份 XML 副本 / 文件名", "Export the full XML copy / file name"), initial, name =>
                Report(document.SaveCopy(Path.Combine(Storage, "Exports"), name.Trim())));
        }
        private static void Copy(bool full)
        {
            ApplyAttributes();
            XElement current = CurrentEvent();
            if (!full && current == null) throw new InvalidOperationException("Select an event first.");
            Clipboard.SetText(full ? document.Text : current.ToString(SaveOptions.DisableFormatting));
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
            Confirm(T("覆盖你导入的本地源文件", "Overwrite the imported local source"), document.SourcePath + "\n" + T("先备份，原文件被外部修改时停止。", "A backup is made first; external changes abort the overwrite."), () => { document.OverwriteSource(Path.Combine(Storage, "Backups")); Report(T("源文件已更新，备份保存在 BaroDialogue/Backups。", "Source updated; backup saved in BaroDialogue/Backups.")); });
        }
    }
}
