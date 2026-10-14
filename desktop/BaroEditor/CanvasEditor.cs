using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Shapes;
using System.Xml.Linq;
using ShapePath = System.Windows.Shapes.Path;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private const double CardWidth = 242, CardHeight = 116;
        private sealed class Edge { public GraphNode From, To; public ShapePath Curve; public Polygon Arrow; public bool Sequence; }
        private readonly List<Edge> edges = new();
        private ShapePath ghost;
        private void RefreshGraph()
        {
            if (canvas == null) return;
            nodes = Model.Nodes(nodeSearch.Text, out bool limited);
            if (string.IsNullOrWhiteSpace(nodeSearch.Text) && Model.Document.Element(Model.Scope).Name.LocalName is "ScriptedEvent" or "TraitorEvent")
            {
                nodes = nodes.Where(n => n.Path != Model.Scope).ToArray(); foreach (var node in nodes) node.Depth = Math.Max(0, node.Depth - 1);
            }
            Model.EnsurePositions(nodes);
            canvas.Children.Clear(); cards.Clear(); cardNodes.Clear(); edges.Clear();
            if (scriptMode) { RefreshScript(); SetStatus(nodes.Count + " 张卡片 · 同级拖动排序 · 点击编辑 · 跨分支使用画布连接"); return; }
            ghost = new ShapePath { Stroke = accent, StrokeThickness = 2, StrokeDashArray = new DoubleCollection { 3, 3 }, IsHitTestVisible = false }; canvas.Children.Add(ghost);
            var map = nodes.ToDictionary(n => n.Path);
            foreach (var node in nodes)
            {
                if (node.Parent == null || !map.TryGetValue(node.Parent, out var parent)) continue;
                var edge = new Edge { From = parent, To = node, Curve = new ShapePath { Stroke = node.Name is "Option" or "Failure" ? amber : B("#65899D"), StrokeThickness = 1.7, IsHitTestVisible = false }, Arrow = new Polygon { Fill = B("#65899D"), IsHitTestVisible = false } };
                edges.Add(edge); canvas.Children.Add(edge.Curve); canvas.Children.Add(edge.Arrow); UpdateEdge(edge);
            }
            foreach (var group in nodes.Where(n => n.Xml.Parent != null && !Catalog.IsContainer(n.Name)).GroupBy(n => n.Xml.Parent))
            {
                if (group.Key.Name.LocalName is not ("ScriptedEvent" or "TraitorEvent" or "Option" or "Success" or "Failure" or "Interrupt")) continue;
                var ordered = group.OrderBy(n => n.Xml.ElementsBeforeSelf().Count()).ToArray();
                for (int i = 1; i < ordered.Length; i++)
                {
                    if (!ReferenceEquals(ordered[i - 1].Xml.ElementsAfterSelf().FirstOrDefault(), ordered[i].Xml)) continue;
                    var edge = new Edge { From = ordered[i - 1], To = ordered[i], Sequence = true, Curve = new ShapePath { Stroke = B("#537B8E"), StrokeThickness = 1.6, StrokeDashArray = new DoubleCollection { 4, 4 }, IsHitTestVisible = false }, Arrow = new Polygon { Fill = B("#537B8E"), IsHitTestVisible = false } };
                    edges.Add(edge); canvas.Children.Add(edge.Curve); canvas.Children.Add(edge.Arrow); UpdateEdge(edge);
                }
            }
            foreach (var node in nodes) MakeCard(node);
            ResizeCanvas(); RefreshScript();
            if (limited) SetStatus("画布仅显示前 400 个节点；请搜索或选择单个事件。", true);
            else SetStatus(nodes.Count + " 个节点 · 实线：分支结构 · 虚线：同级顺序 · Ctrl + 滚轮缩放");
            if (nodes.Count == 0) { var empty = Text("没有匹配的节点\n清空搜索或更换事件", 18, muted); Canvas.SetLeft(empty, 40); Canvas.SetTop(empty, 60); canvas.Children.Add(empty); }
        }
        private void UpdateEdge(Edge edge)
        {
            var from = Model.Positions[edge.From.Xml]; var to = Model.Positions[edge.To.Xml];
            if (edge.Sequence)
            {
                var a = new Point(from.X + CardWidth / 2, from.Y + CardHeight); var b = new Point(to.X + CardWidth / 2, to.Y);
                edge.Curve.Data = new PathGeometry(new[] { new PathFigure(a, new[] { new BezierSegment(new Point(a.X, a.Y + 36), new Point(b.X, b.Y - 36), b, true) }, false) });
                edge.Arrow.Points = new PointCollection { b, new Point(b.X - 4, b.Y - 7), new Point(b.X + 4, b.Y - 7) }; return;
            }
            var start = new Point(from.X + CardWidth, from.Y + CardHeight / 2); var end = new Point(to.X, to.Y + CardHeight / 2);
            double bend = Math.Max(44, Math.Abs(end.X - start.X) * .5);
            edge.Curve.Data = new PathGeometry(new[] { new PathFigure(start, new[] { new BezierSegment(new Point(start.X + bend, start.Y), new Point(end.X - bend, end.Y), end, true) }, false) });
            edge.Arrow.Points = new PointCollection { end, new Point(end.X - 7, end.Y - 4), new Point(end.X - 7, end.Y + 4) };
        }
        private void UpdateEdges(string path) { foreach (var edge in edges.Where(e => e.From.Path == path || e.To.Path == path)) UpdateEdge(edge); }
        private void ResizeCanvas()
        {
            canvas.Width = Math.Max(1100, nodes.Count == 0 ? 1100 : nodes.Max(n => Model.Positions[n.Xml].X) + CardWidth + 100);
            canvas.Height = Math.Max(700, nodes.Count == 0 ? 700 : nodes.Max(n => Model.Positions[n.Xml].Y) + CardHeight + 100);
        }
        private void MakeCard(GraphNode node)
        {
            var panelBody = new Grid(); panelBody.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto }); panelBody.RowDefinitions.Add(new RowDefinition { Height = new GridLength(1, GridUnitType.Star) }); panelBody.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var headline = new DockPanel(); var number = Text(node.Xml.Parent == null ? "根" : (node.Xml.ElementsBeforeSelf().Count() + 1).ToString("00"), 10, muted); DockPanel.SetDock(number, Dock.Right); headline.Children.Add(number); headline.Children.Add(Text(EditorText.Node(node.Name), 14, node.Name is "ConversationAction" ? accent : node.Name is "Option" or "Success" or "Failure" ? amber : ink, true)); At(panelBody, headline);
            var summary = Text(node.Summary.Length > 100 ? node.Summary[..100] + "…" : node.Summary.Length > 0 ? node.Summary : NodeDescription(node.Xml), 12, muted); summary.MaxHeight = 40; summary.TextTrimming = TextTrimming.CharacterEllipsis; summary.Margin = new Thickness(0, 6, 0, 5); At(panelBody, summary, 1); At(panelBody, Text(node.Name, 10, B("#6E8A9B")), 2);
            var card = new Border { Width = CardWidth, Height = CardHeight, Background = panel, BorderBrush = node.Path == Model.Selected ? accent : line, BorderThickness = new Thickness(node.Path == Model.Selected ? 2 : 1), CornerRadius = new CornerRadius(10), Padding = new Thickness(18, 12, 18, 10), Child = panelBody, Cursor = Cursors.SizeAll, AllowDrop = true, ToolTip = EditorText.DisplayNode(node.Name, true) + "\n" + node.Path + "\n拖动摆放；双击编辑文本或 XML" };
            var point = Model.Positions[node.Xml]; Canvas.SetLeft(card, point.X); Canvas.SetTop(card, point.Y); Panel.SetZIndex(card, 2); canvas.Children.Add(card); cards[node.Path] = card; cardNodes.Add((node, card));
            var input = new Button { Content = "●", Padding = new Thickness(2), Width = 22, Height = 24, Background = bg, Foreground = accent, BorderThickness = new Thickness(0), Margin = new Thickness(-29, 0, 0, 0), HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Center, ToolTip = "输入连接：先点击另一节点的输出圆点" };
            var output = new Button { Content = "●", Padding = new Thickness(2), Width = 22, Height = 24, Background = bg, Foreground = accent, BorderThickness = new Thickness(0), Margin = new Thickness(0, 0, -29, 0), HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Center, ToolTip = "拖到另一节点的输入圆点连默认分支；点击可选其他分支" };
            panelBody.Children.Add(input); panelBody.Children.Add(output); Grid.SetRowSpan(input, 3); Grid.SetRowSpan(output, 3);
            bool wiring = false; Point wireStart = new();
            input.Click += (_, _) => Safe(() => CompleteLink(node.Path)); output.Click += (_, _) => { if (!wiring) LinkMenu(node, output); };
            output.PreviewMouseLeftButtonDown += (_, e) => wireStart = e.GetPosition(canvas);
            output.PreviewMouseMove += (_, e) =>
            {
                if (e.LeftButton != MouseButtonState.Pressed) return; var point = e.GetPosition(canvas);
                if (!wiring && (point - wireStart).Length > 4) { CommitInspector(); wiring = true; linkSource = node.Path; linkKind = DefaultLinkKind(node.Name); output.CaptureMouse(); }
                if (wiring) { DrawGhost(point); e.Handled = true; }
            };
            output.PreviewMouseLeftButtonUp += (_, e) =>
            {
                if (!wiring) return; var point = e.GetPosition(canvas); output.ReleaseMouseCapture();
                var target = nodes.FirstOrDefault(n => { var position = Model.Positions[n.Xml]; return (new Point(position.X, position.Y + CardHeight / 2) - point).Length < 22; });
                if (target != null) Safe(() => CompleteLink(target.Path)); else { linkSource = null; ghost.Data = null; SetStatus("连接已取消：请放到目标左侧圆点。"); }
                e.Handled = true; Dispatcher.BeginInvoke(new Action(() => wiring = false));
            };
            card.MouseLeftButtonDown += (_, e) =>
            {
                if (e.OriginalSource is FrameworkElement origin && FindAncestor<Button>(origin) != null) return;
                Safe(() => SelectNode(node.Path));
                if (e.ClickCount == 2) { Safe(EditNode); e.Handled = true; return; }
                BeginDrag(node, e.GetPosition(canvas)); card.CaptureMouse(); e.Handled = true;
            };
            card.MouseMove += (_, e) =>
            {
                if (dragging == node && e.LeftButton == MouseButtonState.Pressed && card.IsMouseCaptured) { DragTo(e.GetPosition(canvas)); e.Handled = true; }
                else if (linkSource != null) DrawGhost(e.GetPosition(canvas));
            };
            card.MouseLeftButtonUp += (_, e) => { if (dragging == node) { EndDrag(); card.ReleaseMouseCapture(); e.Handled = true; } };
            card.LostMouseCapture += (_, _) => { if (dragging == node) EndDrag(); };
            card.Drop += (_, e) => { if (!e.Data.GetDataPresent("BaroEditor.Action")) return; Safe(() => AddAction((string)e.Data.GetData("BaroEditor.Action"), node.Path, e.GetPosition(canvas))); e.Handled = true; };
            card.DragOver += (_, e) => { e.Effects = e.Data.GetDataPresent("BaroEditor.Action") ? DragDropEffects.Copy : DragDropEffects.None; e.Handled = true; };
        }
        private static T FindAncestor<T>(DependencyObject element) where T : DependencyObject { for (var item = element; item != null; item = item is Visual ? VisualTreeHelper.GetParent(item) : LogicalTreeHelper.GetParent(item)) if (item is T typed) return typed; return null; }
        private string NodeDescription(XElement node) => string.Join(" · ", node.Attributes().Where(a => !a.IsNamespaceDeclaration).Take(2).Select(a => EditorText.Property(a.Name.LocalName) + " " + a.Value));
        internal void BeginDrag(GraphNode node, Point origin)
        {
            dragging = node; dragOrigin = origin; var point = Model.Positions[node.Xml]; nodeOrigin = new Point(point.X, point.Y); dragBefore = Model.CapturePositions(); didDrag = false;
        }
        internal void DragTo(Point point)
        {
            if (dragging == null) return; var delta = point - dragOrigin; if (delta.Length > 3) didDrag = true;
            var position = Model.Positions[dragging.Xml]; position.X = Math.Clamp(nodeOrigin.X + delta.X, 0, 50000); position.Y = Math.Clamp(nodeOrigin.Y + delta.Y, 0, 50000);
            if (cards.TryGetValue(dragging.Path, out var card)) { Canvas.SetLeft(card, position.X); Canvas.SetTop(card, position.Y); } UpdateEdges(dragging.Path);
        }
        internal void EndDrag()
        {
            if (dragging == null) return; if (didDrag) { Model.LayoutEdited(dragBefore); ResizeCanvas(); RefreshHeader(); SetStatus("节点位置已修改 · XML 内容保留 · 保存工程可保留布局"); } dragging = null; dragBefore = null;
#if INTERACTION
            SaveInteractionProbe("drag");
#endif
        }
        private void DrawGhost(Point end)
        {
            var source = nodes.FirstOrDefault(n => n.Path == linkSource); if (source == null || ghost == null) return;
            var point = Model.Positions[source.Xml]; var start = new Point(point.X + CardWidth, point.Y + CardHeight / 2); ghost.Data = new PathGeometry(new[] { new PathFigure(start, new[] { new BezierSegment(new Point(start.X + 80, start.Y), new Point(end.X - 80, end.Y), end, true) }, false) });
        }
        private void LinkMenu(GraphNode node, Button button)
        {
            var menu = new ContextMenu { Background = panel, Foreground = ink };
            var kinds = node.Name == "ConversationAction" ? new[] { ("新选项分支", "Option"), ("中断分支", "Interrupt"), ("下一动作（同级）", "next") } :
                node.Name.StartsWith("Check") || node.Name is "RNGAction" or "SkillCheckAction" ? new[] { ("成功分支", "Success"), ("失败分支", "Failure"), ("下一动作（同级）", "next") } :
                Catalog.IsContainer(node.Name) ? new[] { ("子节点", "child"), ("下一节点（同级）", "next") } : new[] { ("下一动作（同级）", "next"), ("XML 子节点（高级）", "child") };
            foreach (var (label, kind) in kinds) { var entry = new MenuItem { Header = "连接 → " + label }; entry.Click += (_, _) => { CommitInspector(); linkSource = node.Path; linkKind = kind; SetStatus("点击目标节点的左侧圆点，连接为“" + label + "”；Esc 取消"); }; menu.Items.Add(entry); }
            menu.PlacementTarget = button; menu.IsOpen = true;
        }
        private static string DefaultLinkKind(string name) => name == "ConversationAction" ? "Option" : name.StartsWith("Check") || name is "RNGAction" or "SkillCheckAction" ? "Success" : Catalog.IsContainer(name) ? "child" : "next";
        private void CompleteLink(string target)
        {
            if (linkSource == null) { SelectNode(target); SetStatus("先点击来源节点右侧圆点，再选择连接方式。"); return; }
            string source = linkSource, kind = linkKind; linkSource = null; if (ghost != null) ghost.Data = null;
            CommitInspector(); Model.Connect(source, target, kind); RefreshAll(); SetStatus("已更新 XML 结构连接 · 可撤销");
#if INTERACTION
            SaveInteractionProbe("connect");
#endif
        }
        private void CanvasDrop(object sender, DragEventArgs e)
        {
            if (!e.Data.GetDataPresent("BaroEditor.Action")) return; Safe(() => AddAction((string)e.Data.GetData("BaroEditor.Action"), Model.Selected, e.GetPosition(canvas))); e.Handled = true;
        }
        private void AddAction(string name, string target, Point? point = null)
        {
            CommitInspector(); var node = Model.Document.Element(target);
            string parent = Catalog.IsContainer(node.Name.LocalName) ? target : node.Parent != null ? Model.Document.PathOf(node.Parent) : target;
            var attributes = name == "ConversationAction" ? new Dictionary<string, string> { ["text"] = "在这里写台词", ["targettag"] = "player" } : name == "Option" ? new Dictionary<string, string> { ["text"] = "选项文本" } : null;
            var added = Model.Add(parent, name, point is Point p ? new NodePosition { X = Math.Max(0, p.X), Y = Math.Max(0, p.Y) } : null, attributes);
            RefreshAll(); SetStatus("已添加 " + EditorText.Node(name) + " · " + name);
        }
        private void SelectNode(string path)
        {
            CommitInspector(); Model.Select(path); foreach (var card in cards) { card.Value.BorderBrush = card.Key == path ? accent : line; card.Value.BorderThickness = new Thickness(card.Key == path ? 2 : 1); } RefreshInspector(); if (inspectorMode == "xml") RefreshXml();
        }
        private void Arrange() { CommitInspector(); var before = Model.CapturePositions(); Model.Arrange(nodes); Model.LayoutEdited(before); RefreshAll(); }
        private void Fit()
        {
            if (scriptMode || nodes.Count == 0) return; zoom.Value = Math.Clamp(Math.Min(graphScroll.ViewportWidth / canvas.Width, graphScroll.ViewportHeight / canvas.Height), .25, 1.2); graphScroll.ScrollToHorizontalOffset(0); graphScroll.ScrollToVerticalOffset(0);
        }
        private void RefreshHeader() { undo.IsEnabled = Model.CanUndo; redo.IsEnabled = Model.CanRedo; documentLabel.Text = (projectPath == null ? "事件草稿" : System.IO.Path.GetFileName(projectPath)) + " · " + (Model.ProjectDirty ? "有修改" : "已保存") + " · 原生 XML"; }
        private void RefreshScript()
        {
            if (script == null) return; script.Children.Clear(); if (!scriptMode) return;
            foreach (var node in nodes)
            {
                var body = new StackPanel(); var title = new DockPanel(); var edit = Btn("编辑", () => { SelectNode(node.Path); EditNode(); }); DockPanel.SetDock(edit, Dock.Right); title.Children.Add(edit); title.Children.Add(Text(EditorText.Node(node.Name), 14, node.Name == "ConversationAction" ? accent : ink, true)); body.Children.Add(title); body.Children.Add(Text(node.Summary.Length > 200 ? node.Summary[..200] + "…" : node.Summary.Length > 0 ? node.Summary : NodeDescription(node.Xml), 13, muted)); body.Children.Add(Text(node.Name + " · " + node.Path, 10, muted));
                var row = Box(body); row.Margin = new Thickness(Math.Min(node.Depth, 6) * 16, 0, 0, 10); row.BorderBrush = node.Path == Model.Selected ? accent : line; row.Cursor = Cursors.Hand; row.AllowDrop = true;
                row.MouseLeftButtonDown += (_, e) => { if (e.OriginalSource is DependencyObject source && FindAncestor<Button>(source) != null) return; Safe(() => SelectNode(node.Path)); scriptDown = e.GetPosition(row); scriptDragPath = node.Path; };
                row.MouseMove += (_, e) => { if (scriptDown is Point start && e.LeftButton == MouseButtonState.Pressed && (e.GetPosition(row) - start).Length > 8) { scriptDown = null; DragDrop.DoDragDrop(row, new DataObject("BaroEditor.Node", scriptDragPath), DragDropEffects.Move); } };
                row.MouseLeftButtonUp += (_, _) => scriptDown = null;
                row.Drop += (_, e) => Safe(() =>
                {
                    CommitInspector();
                    if (e.Data.GetDataPresent("BaroEditor.Node")) { string from = (string)e.Data.GetData("BaroEditor.Node"); var source = Model.Document.Element(from); if (!ReferenceEquals(source.Parent, node.Xml.Parent)) throw new InvalidOperationException("剧本卡片拖动排序需要同级节点；跨分支请用画布连线。"); Model.Change(doc => doc.Relocate(from, doc.PathOf(node.Xml.Parent), node.Xml.ElementsBeforeSelf().Count())); RefreshAll(); }
                    else if (e.Data.GetDataPresent("BaroEditor.Action")) AddAction((string)e.Data.GetData("BaroEditor.Action"), node.Path);
                    e.Handled = true;
                });
                script.Children.Add(row);
            }
            if (nodes.Count == 0) script.Children.Add(Text("没有匹配的节点", 14, muted));
        }
    }
}
