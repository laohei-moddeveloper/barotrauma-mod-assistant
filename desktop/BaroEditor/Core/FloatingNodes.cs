using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;

namespace BaroEditor
{
    public sealed partial class Workspace
    {
        private const string DraftPrefix = "$draft/", GroupName = "BaroEditorDraftGroup";
        private EventDocument draft;
        private EventSearch draftSearch;
        private long draftSearchRevision = -1, draftLocaleRevision = -1;
        private XDocument groupCacheDocument;
        private long groupCacheRevision = -1;
        private Dictionary<string, XElement> groups = new();
        private readonly Dictionary<XElement,Dictionary<string,List<XElement>>> labelIndexes=new();
        private XDocument labelMainDocument,labelDraftDocument;
        private long labelMainRevision=-1,labelDraftRevision=-1;
        public bool IsFloating(string path) => path?.StartsWith(DraftPrefix, StringComparison.Ordinal) == true;
        public int FloatingCount => draft.Xml.Root.Elements().Count(g => g.HasElements);
        public bool HasFloating => FloatingCount > 0;
        public EventDocument SelectedDocument => IsFloating(Selected) ? draft : Document;
        public string SelectedLocalPath => SelectedDocument.PathOf(Current);
        private bool IsLive(XElement node) => ReferenceEquals(node.Document, Document.Xml) || ReferenceEquals(node.Document, draft.Xml);
        private void IndexGroups()
        {
            if (ReferenceEquals(groupCacheDocument, draft.Xml) && groupCacheRevision == draft.Revision) return;
            groups = draft.Xml.Root.Elements().ToDictionary(g => EventDocument.Attribute(g,"id"), StringComparer.Ordinal);
            groupCacheDocument=draft.Xml; groupCacheRevision=draft.Revision;
        }
        public XElement Element(string path)
        {
            if (!IsFloating(path)) return Document.Element(path);
            IndexGroups(); string[] parts=path[DraftPrefix.Length..].Split('/');
            if (!groups.TryGetValue(parts[0],out var node)) throw new InvalidDataException("悬空节点已不存在。");
            foreach (string part in parts.Skip(1))
            {
                if (!int.TryParse(part,out int index) || index<0 || (node=node.Elements().ElementAtOrDefault(index))==null) throw new InvalidDataException("悬空节点路径无效。");
            }
            return node;
        }
        public string PathOf(XElement node)
        {
            if (ReferenceEquals(node.Document,Document.Xml)) return Document.PathOf(node);
            if (!ReferenceEquals(node.Document,draft.Xml)) throw new InvalidDataException("节点已不在工程中。");
            var group=node.AncestorsAndSelf().FirstOrDefault(e=>e.Name.LocalName==GroupName && ReferenceEquals(e.Parent,draft.Xml.Root));
            if (group==null) throw new InvalidDataException("不能选择工程的草稿容器。");
            string local=draft.PathOf(node), groupPath=draft.PathOf(group);
            return DraftPrefix+EventDocument.Attribute(group,"id")+local[groupPath.Length..];
        }
        private static EventDocument ReadDraft(string xml)
        {
            var result=new EventDocument(xml??"<BaroEditorDrafts/>");
            if (result.Xml.Root.Name != "BaroEditorDrafts") throw new InvalidDataException("工程草稿根节点无效。");
            var ids=new HashSet<string>(StringComparer.Ordinal);
            foreach(var group in result.Xml.Root.Elements())
            {
                string id=EventDocument.Attribute(group,"id"),scope=EventDocument.Attribute(group,"scope");
                if(group.Name!=GroupName || !Guid.TryParseExact(id,"N",out _) || !ids.Add(id) || scope.Length>640 || scope.StartsWith(DraftPrefix,StringComparison.Ordinal)) throw new InvalidDataException("工程悬空草稿无效。");
            }
            return result;
        }
        private void AppendFloating(List<GraphNode> list,string query,int limit,ref bool limited)
        {
            HashSet<string> matches=null;
            if(!string.IsNullOrWhiteSpace(query))
            {
                if(draftSearch==null || draftSearchRevision!=draft.Revision || draftLocaleRevision!=Localization.Revision)
                { draftSearch=new EventSearch(draft.Xml.Root,Localization.SearchText); draftSearchRevision=draft.Revision; draftLocaleRevision=Localization.Revision; }
                matches=draftSearch.Find(query,"",out _,out _,300);
            }
            var eligible=draft.Xml.Root.Elements().Where(g=>Scope.Length==0 || EventDocument.Attribute(g,"scope")==Scope || IsFloating(Selected) && Selected.StartsWith(DraftPrefix+EventDocument.Attribute(g,"id")+"/",StringComparison.Ordinal)).ToArray();
            // A selected draft group goes first and cannot disappear behind the component cap.
            foreach(var group in eligible.OrderByDescending(g=>IsFloating(Selected) && Selected.StartsWith(DraftPrefix+EventDocument.Attribute(g,"id")+"/",StringComparison.Ordinal)))
            {
                var pending=new Stack<(XElement Node,string Parent,int Depth)>();
                foreach(var root in group.Elements().Reverse()) pending.Push((root,null,0));
                while(pending.Count>0)
                {
                    var item=pending.Pop(); if(matches!=null && !matches.Contains(draft.PathOf(item.Node))) continue;
                    if(list.Count>=limit) { limited=true; return; }
                    string path=PathOf(item.Node);
                    list.Add(new GraphNode { Xml=item.Node,Path=path,Parent=item.Parent,Depth=item.Depth,Floating=true });
                    foreach(var child in item.Node.Elements().Reverse()) pending.Push((child,path,item.Depth+1));
                }
            }
        }
        private void ChangeIn(EventDocument editor,Action<EventDocument> action)
        {
            var before=CapturePositions(); string oldSelection=Selected,oldScope=Scope; var oldNode=Current;
            long mainRevision=Document.Revision,draftRevision=draft.Revision;
            try { action(editor); }
            catch { Restore(before); ValidateSelection(); throw; }
            bool nativeChanged=mainRevision!=Document.Revision,draftChanged=draftRevision!=draft.Revision;
            if(!nativeChanged && !draftChanged) return;
            foreach(var orphan in Positions.Keys.Where(n=>!IsLive(n)).ToArray()) Positions.Remove(orphan);
            if(IsLive(oldNode)) Selected=PathOf(oldNode);
            ValidateSelection(); EnsurePositions(Nodes("",out _));
            undo.Add(new Edit { Xml=nativeChanged,Draft=draftChanged,Before=before,After=CapturePositions(),SelectionBefore=oldSelection,SelectionAfter=Selected,ScopeBefore=oldScope,ScopeAfter=Scope }); TrimHistory(); redo.Clear();
        }
        public string AddFloating(string name,NodePosition position,IDictionary<string,string> attributes=null)
        {
            System.Xml.XmlConvert.VerifyNCName(name); string id=Guid.NewGuid().ToString("N"),path=DraftPrefix+id+"/0";
            var action=new XElement(Document.Element(Scope).Name.Namespace+name);
            if(attributes!=null) foreach(var entry in attributes) action.SetAttributeValue(XName.Get(entry.Key),entry.Value);
            var group=new XElement(GroupName,new XAttribute("id",id),new XAttribute("scope",Scope),action);
            ChangeIn(draft,doc=>doc.EditTree(xml=>{ xml.Root.Add(group); Positions[action]=position??new NodePosition{X=36,Y=36}; }));
            Select(path); FinalizeSelection(); return path;
        }
        public void DetachSelected()
        {
            if(IsFloating(Selected)) return;
            var node=Current; if(ReferenceEquals(node,Document.Xml.Root) || node.Name.LocalName is "ScriptedEvent" or "TraitorEvent") throw new InvalidDataException("事件根节点不能转为悬空动作。");
            string id=Guid.NewGuid().ToString("N");
            ChangeIn(Document,doc=>doc.EditTree(_=>draft.EditTree(xml=>{ node.Remove(); xml.Root.Add(new XElement(GroupName,new XAttribute("id",id),new XAttribute("scope",Scope),node)); })));
            Select(PathOf(node)); FinalizeSelection();
        }
        private void ConnectFloating(string source,string target,string kind)
        {
            if(source==target) throw new InvalidDataException("节点不能连接到自己。");
            var from=Element(source); var to=Element(target);
            if(from.Ancestors().Contains(to)) throw new InvalidDataException("连接会把祖先放进后代，形成循环。");
            if(to.Parent==null) throw new InvalidDataException("文件根节点不能移动到动作内。");
            var sourceDocument=IsFloating(source)?draft:Document; var targetDocument=IsFloating(target)?draft:Document;
            EventStructure.RequirePlacement(kind=="next"?from.Parent??from:from,new[]{to});
            // An unattached sequential chain attaches as a whole, including its trailing siblings.
            var moving=to.Parent.Name.LocalName==GroupName && !ReferenceEquals(from.Parent,to.Parent)?new[]{to}.Concat(to.ElementsAfterSelf()).ToArray():new[]{to};
            if(moving.Any(n=>ReferenceEquals(n,from) || from.Ancestors().Contains(n))) throw new InvalidDataException("连接会形成循环。");
            void MoveTree()
            {
                XElement parent;
                if(kind=="next") parent=from.Parent??throw new InvalidDataException("根节点没有下一同级动作。");
                else
                {
                    parent=from;
                    if(kind!="child")
                    {
                        if(kind is not ("Option" or "Success" or "Failure" or "Interrupt")) throw new InvalidDataException("不支持的分支。");
                        var branch=kind=="Option"?null:parent.Elements(parent.Name.Namespace+kind).FirstOrDefault();
                        if(branch==null) { branch=new XElement(parent.Name.Namespace+kind); if(kind=="Option") branch.SetAttributeValue("text","继续"); parent.Add(branch); }
                        parent=branch;
                    }
                }
                if(moving.Any(n=>ReferenceEquals(n,parent) || parent.Ancestors().Contains(n))) throw new InvalidDataException("连接会形成循环。");
                foreach(var node in moving) node.Remove();
                if(kind=="next") from.AddAfterSelf(moving); else parent.Add(moving);
            }
            ChangeIn(targetDocument,_=>
            {
                if(ReferenceEquals(sourceDocument,targetDocument)) sourceDocument.EditTree(_=>MoveTree());
                else targetDocument.EditTree(_=>sourceDocument.EditTree(_=>MoveTree()));
            });
            Select(PathOf(to)); FinalizeSelection();
        }
        public void RequireConnected()
        {
            if(EventStructure.Violations(Document.Xml.Root).Any()) throw new InvalidDataException("事件组和脚本事件不能嵌套在事件内部，请先修正结构再输出 XML。");
            if(HasFloating) throw new InvalidDataException($"还有 {FloatingCount} 组草稿未接入事件。请先连接或删除，再导出/复制 XML。保存工程会保留这些悬空节点。");
        }
        public IReadOnlyList<XElement> GoToTargets(string path)
        {
            var node=Element(path); if(!node.Name.LocalName.Equals("GoTo",StringComparison.OrdinalIgnoreCase)) return Array.Empty<XElement>();
            string name=EventDocument.Attribute(node,"name"); if(name.Length==0) return Array.Empty<XElement>();
            var scope=node.AncestorsAndSelf().FirstOrDefault(n=>n.Name.LocalName is "ScriptedEvent" or "TraitorEvent") ?? node.Ancestors().FirstOrDefault(n=>n.Name.LocalName==GroupName) ?? Document.Xml.Root;
            if(!ReferenceEquals(labelMainDocument,Document.Xml) || !ReferenceEquals(labelDraftDocument,draft.Xml) || labelMainRevision!=Document.Revision || labelDraftRevision!=draft.Revision)
            { labelIndexes.Clear(); labelMainDocument=Document.Xml; labelDraftDocument=draft.Xml; labelMainRevision=Document.Revision; labelDraftRevision=draft.Revision; }
            if(!labelIndexes.TryGetValue(scope,out var labels))
            {
                labels=scope.DescendantsAndSelf().Where(n=>n.Name.LocalName.Equals("Label",StringComparison.OrdinalIgnoreCase)).GroupBy(n=>EventDocument.Attribute(n,"name"),StringComparer.OrdinalIgnoreCase).ToDictionary(g=>g.Key,g=>g.ToList(),StringComparer.OrdinalIgnoreCase); labelIndexes[scope]=labels;
            }
            return labels.TryGetValue(name,out var targets)?targets:Array.Empty<XElement>();
        }
    }
}
