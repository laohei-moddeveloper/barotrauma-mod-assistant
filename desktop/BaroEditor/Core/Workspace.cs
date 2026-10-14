using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Xml.Linq;

namespace BaroEditor
{
    public sealed class NodePosition { public double X { get; set; } public double Y { get; set; } }
    public sealed class ProjectFile
    {
        public int FormatVersion { get; set; } = 1;
        public string Xml { get; set; }
        public string Scope { get; set; }
        public string Selected { get; set; }
        public Dictionary<string, NodePosition> Positions { get; set; } = new();
    }
    public sealed class GraphNode
    {
        public string Path, Parent;
        public XElement Xml;
        public int Depth;
        public string Name => Xml.Name.LocalName;
        public string Summary => EventDocument.Attribute(Xml, "text") is string text && text.Length > 0 ? text : EventDocument.Attribute(Xml, "identifier");
    }
    public sealed class Workspace
    {
        public EventDocument Document { get; private set; }
        public string Scope { get; private set; } = "";
        public string Selected { get; private set; } = "";
        public Dictionary<XElement, NodePosition> Positions { get; } = new();
        private EventSearch search;
        private long searchRevision = -1;
        private readonly List<(bool Xml, Dictionary<string, NodePosition> Before, Dictionary<string, NodePosition> After, string SelectionBefore, string SelectionAfter)> undo = new(), redo = new();
        private string savedProject;
        public bool CanUndo => undo.Count > 0;
        public bool CanRedo => redo.Count > 0;
        public Workspace(EventDocument document) { Load(document); }
        public void Load(EventDocument document)
        {
            Document = document; Scope = document.EventEntries().FirstOrDefault().Path ?? ""; Selected = Scope;
            Positions.Clear(); undo.Clear(); redo.Clear(); search = null; savedProject = null;
        }
        public XElement Current => Document.Element(Selected);
        public void Select(string path) { Document.Element(path); Selected = path; }
        public void SetScope(string path) { Document.Element(path); Scope = path; Selected = path; }
        public IReadOnlyList<GraphNode> Nodes(string query, out bool limited, int limit = 400)
        {
            HashSet<string> visible = null;
            if (!string.IsNullOrWhiteSpace(query))
            {
                if (search == null || searchRevision != Document.Revision) { search = new EventSearch(Document.Xml.Root); searchRevision = Document.Revision; }
                visible = search.Find(query, Scope, out _, out _, 300);
            }
            var list = new List<GraphNode>(); var stack = new Stack<(XElement Xml, string Path, string Parent, int Depth)>();
            stack.Push((Document.Element(Scope), Scope, null, 0)); limited = false;
            while (stack.Count > 0)
            {
                var item = stack.Pop();
                if (visible != null && !visible.Contains(item.Path)) continue;
                if (list.Count >= limit) { limited = true; break; }
                list.Add(new GraphNode { Xml = item.Xml, Path = item.Path, Parent = item.Parent, Depth = item.Depth });
                var children = item.Xml.Elements().ToArray();
                for (int i = children.Length - 1; i >= 0; i--) stack.Push((children[i], item.Path.Length == 0 ? i.ToString() : item.Path + "/" + i, item.Path, item.Depth + 1));
            }
            if (visible == null && limited && !list.Any(n => n.Path == Selected) && (Scope.Length == 0 || Selected == Scope || Selected.StartsWith(Scope + "/", StringComparison.Ordinal)))
            {
                foreach (var node in Current.AncestorsAndSelf().Reverse())
                {
                    string path = Document.PathOf(node);
                    if (Scope.Length > 0 && path != Scope && !path.StartsWith(Scope + "/", StringComparison.Ordinal) || list.Any(n => n.Path == path)) continue;
                    if (list.Count >= limit) list.RemoveAt(list.Count - 1);
                    int depth = path.Length == 0 ? 0 : path.Split('/').Length; depth -= Scope.Length == 0 ? 0 : Scope.Split('/').Length;
                    list.Add(new GraphNode { Xml = node, Path = path, Parent = node.Parent == null ? null : Document.PathOf(node.Parent), Depth = depth });
                }
            }
            return list;
        }
        public void Arrange(IReadOnlyList<GraphNode> nodes)
        {
            var children = nodes.Where(n => n.Parent != null).GroupBy(n => n.Parent).ToDictionary(g => g.Key, g => g.ToArray());
            double nextY = 36;
            double Visit(GraphNode node)
            {
                double y;
                if (children.TryGetValue(node.Path, out var descendants))
                {
                    var ys = descendants.Select(Visit).ToArray(); y = ys.First();
                }
                else { y = nextY; nextY += 150; }
                Positions[node.Xml] = new NodePosition { X = 36 + node.Depth * 286, Y = y }; return y;
            }
            foreach (var root in nodes.Where(n => n.Parent == null || !nodes.Any(p => p.Path == n.Parent))) Visit(root);
        }
        public void EnsurePositions(IReadOnlyList<GraphNode> nodes)
        {
            if (nodes.All(n => Positions.ContainsKey(n.Xml))) return;
            var previous = Positions.ToDictionary(p => p.Key, p => p.Value);
            Arrange(nodes); foreach (var node in nodes) if (previous.TryGetValue(node.Xml, out var point)) Positions[node.Xml] = point;
            foreach (var node in nodes.Where(n => !previous.ContainsKey(n.Xml)))
            {
                var point = Positions[node.Xml];
                while (nodes.Any(other => !ReferenceEquals(node.Xml, other.Xml) && Math.Abs(Positions[other.Xml].X - point.X) < 250 && Math.Abs(Positions[other.Xml].Y - point.Y) < 130)) point.Y += 150;
            }
        }
        public Dictionary<string, NodePosition> CapturePositions() => Positions.Where(p => ReferenceEquals(p.Key.Document, Document.Xml)).ToDictionary(p => Document.PathOf(p.Key), p => new NodePosition { X = p.Value.X, Y = p.Value.Y });
        private void Restore(Dictionary<string, NodePosition> points)
        {
            Positions.Clear(); foreach (var point in points) { try { Positions[Document.Element(point.Key)] = new NodePosition { X = point.Value.X, Y = point.Value.Y }; } catch (InvalidDataException) { } }
        }
        public void LayoutEdited(Dictionary<string, NodePosition> before)
        {
            var after = CapturePositions(); if (JsonSerializer.Serialize(before) == JsonSerializer.Serialize(after)) return;
            undo.Add((false, before, after, Selected, Selected)); TrimHistory(); redo.Clear();
        }
        private void TrimHistory() { while (undo.Count > 24) undo.RemoveAt(0); }
        public void Change(Action<EventDocument> action)
        {
            var before = CapturePositions(); string oldSelection = Selected; XElement oldNode = Current; long revision = Document.Revision;
            action(Document); if (revision == Document.Revision) return;
            foreach (var orphan in Positions.Keys.Where(n => !ReferenceEquals(n.Document, Document.Xml)).ToArray()) Positions.Remove(orphan);
            if (ReferenceEquals(oldNode.Document, Document.Xml)) Selected = Document.PathOf(oldNode);
            else { try { Document.Element(Selected); } catch { Selected = Scope; } }
            try { Document.Element(Scope); } catch { Scope = ""; }
            EnsurePositions(Nodes("", out _));
            undo.Add((true, before, CapturePositions(), oldSelection, Selected)); TrimHistory(); redo.Clear();
        }
        public void Undo()
        {
            if (!CanUndo) return; var edit = undo[^1];
            if (edit.Xml) { if (!Document.CanUndo) throw new InvalidOperationException("这次 XML 修改超过历史预算，无法撤销。"); Document.Undo(); }
            undo.RemoveAt(undo.Count - 1); redo.Add(edit); Restore(edit.Before); Selected = edit.SelectionBefore; ValidateSelection();
        }
        public void Redo()
        {
            if (!CanRedo) return; var edit = redo[^1];
            if (edit.Xml) { if (!Document.CanRedo) return; Document.Redo(); }
            redo.RemoveAt(redo.Count - 1); undo.Add(edit); Restore(edit.After); Selected = edit.SelectionAfter; ValidateSelection();
        }
        private void ValidateSelection() { try { Document.Element(Scope); } catch { Scope = ""; } try { Document.Element(Selected); } catch { Selected = Scope; } }
        public string Add(string parent, string name, NodePosition position = null, IDictionary<string, string> attributes = null)
        {
            string added = null;
            Change(doc => { var node = doc.Element(parent); int index = node.Elements().Count(); doc.AddChild(parent, name, attributes); added = parent.Length == 0 ? index.ToString() : parent + "/" + index; if (position != null) Positions[doc.Element(added)] = position; });
            Select(added); EnsurePositions(Nodes("", out _)); FinalizeSelection(); return added;
        }
        public void FinalizeSelection()
        {
            if (undo.Count == 0) return; var edit = undo[^1]; undo[^1] = (edit.Xml, edit.Before, CapturePositions(), edit.SelectionBefore, Selected);
        }
        public void Connect(string source, string target, string kind)
        {
            if (source == target) throw new InvalidOperationException("节点不能连接到自己。");
            var sourceNode = Document.Element(source); var targetNode = Document.Element(target);
            if (sourceNode.Ancestors().Contains(targetNode)) throw new InvalidOperationException("连接会把祖先放进后代，形成循环，已取消。");
            Change(doc =>
            {
                if (kind == "next")
                {
                    if (sourceNode.Parent == null) throw new InvalidOperationException("根节点没有同级后续动作。");
                    var parent = sourceNode.Parent; int sourceIndex = sourceNode.ElementsBeforeSelf().Count();
                    if (ReferenceEquals(targetNode.Parent, parent) && targetNode.ElementsBeforeSelf().Count() < sourceIndex) sourceIndex--;
                    Selected = doc.Relocate(target, doc.PathOf(parent), sourceIndex + 1);
                }
                else Selected = doc.Relocate(target, source, branch: kind == "child" ? null : kind);
            });
            Select(Document.PathOf(targetNode));
            FinalizeSelection();
        }
        public ProjectFile Snapshot() => new() { Xml = Document.Text, Scope = Scope, Selected = Selected, Positions = CapturePositions() };
        public bool ProjectDirty => savedProject != null ? savedProject != JsonSerializer.Serialize(Snapshot()) : Document.Dirty || undo.Count > 0;
        public void SaveProject(string path)
        {
            string text = JsonSerializer.Serialize(Snapshot()); WriteProject(path, text); savedProject = text;
        }
        public void ReadProject(string path)
        {
            if (new FileInfo(path).Length > 64 * 1024 * 1024) throw new InvalidDataException("工程超过 64 MiB。");
            var project = JsonSerializer.Deserialize<ProjectFile>(File.ReadAllText(path));
            if (project?.FormatVersion != 1 || project.Positions == null || project.Positions.Count > EventDocument.MaxElements) throw new InvalidDataException("不支持的工程格式。");
            if (project.Positions.Keys.Any(k => k.Length > 640) || (project.Scope?.Length ?? 0) > 640 || (project.Selected?.Length ?? 0) > 640) throw new InvalidDataException("工程路径长度无效。");
            var document = new EventDocument(project.Xml);
            foreach (var p in project.Positions.Values) if (!double.IsFinite(p.X) || !double.IsFinite(p.Y) || p.X < 0 || p.Y < 0 || p.X > 100000 || p.Y > 100000) throw new InvalidDataException("工程坐标无效。");
            Load(document); Scope = project.Scope ?? ""; Selected = project.Selected ?? Scope; ValidateSelection(); Restore(project.Positions); savedProject = JsonSerializer.Serialize(Snapshot());
        }
        private static void WriteProject(string path, string text)
        {
            string target = Path.GetFullPath(path), temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try { File.WriteAllText(temporary, text, new System.Text.UTF8Encoding(false)); if (File.Exists(target)) File.Copy(target, target + ".previous", true); File.Move(temporary, target, true); }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
    }
}
