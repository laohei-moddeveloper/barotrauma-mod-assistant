using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using BaroEditor;

internal static class StandaloneTests
{
    private static int checks;
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); checks++; }
    private static void Throws(Action action, string message) { try { action(); } catch { checks++; return; } throw new Exception(message); }
    public static int Main(string[] args)
    {
        try
        {
            string scratch = Path.GetFullPath(args[0]); Directory.CreateDirectory(scratch);
            var catalog = Catalog.Load(args[1]); Check(catalog.Actions.Length == 66, "All 66 native Actions available offline");
            Check(catalog.Actions.Sum(a => a.Properties.Length) == 313, "All 313 native serialized properties available");
            var all = new Workspace(new EventDocument("<ScriptedEvent identifier='all'><!--keep--></ScriptedEvent>"));
            foreach (var action in catalog.Actions)
            {
                string path = all.Add("", action.Name);
                Check(all.Document.Element(path).Name.LocalName == action.Name, "Canvas supports native Action: " + action.Name);
                Check(catalog.Properties(action.Name).Length == action.Properties.Length, "Properties for Action: " + action.Name);
            }
            Check(all.Document.Text.Contains("<!--keep-->"), "Adding all Actions retains comments");
            var nodes = all.Nodes("", out bool limited); Check(nodes.Count == 67 && !limited, "All added Actions have graph nodes");
            all.Arrange(nodes); Check(all.Positions.Count == 67, "Every Action has a draggable position");
            string xmlBefore = all.Document.Text; var before = all.CapturePositions(); var moved = nodes[4].Xml; double oldX = all.Positions[moved].X;
            all.Positions[moved].X += 170; all.LayoutEdited(before); Check(all.Document.Text == xmlBefore, "Dragging positions never edits XML");
            all.Undo(); Check(all.Positions[moved].X == oldX, "Layout undo"); all.Redo(); Check(all.Positions[moved].X == oldX + 170, "Layout redo");
            string project = Path.Combine(scratch, "roundtrip.baroeditor"); all.SaveProject(project); Check(!all.ProjectDirty, "Project save marks XML and layout clean");
            var restored = new Workspace(new EventDocument("<a/>")); restored.ReadProject(project);
            Check(XNode.DeepEquals(all.Document.Xml, restored.Document.Xml), "Project XML roundtrip");
            Check(restored.CapturePositions().Count == 67 && restored.CapturePositions()[all.Document.PathOf(moved)].X == oldX + 170, "Project layout roundtrip");
            Check(!restored.ProjectDirty && restored.Document.SourcePath == null, "Project load does not read or expose a writable external source");
            all.SaveProject(project); Check(File.Exists(project + ".previous"), "Project overwrite retains previous file");
            var graph = new Workspace(new EventDocument("<ScriptedEvent><CheckMoneyAction amount='1'/><WaitAction time='2' custom='keep'><!--inside--></WaitAction><ConversationAction text='hello'/><WaitAction time='3'/></ScriptedEvent>"));
            graph.Select("0"); string initial = graph.Document.Text;
            graph.Connect("0", "1", "Failure");
            Check(graph.Document.Element("0/0/0").Name.LocalName == "WaitAction" && graph.Document.Element("0/0").Name.LocalName == "Failure", "Visual failure port creates a native branch");
            Check(graph.Document.Text.Contains("custom=\"keep\"") && graph.Document.Text.Contains("<!--inside-->"), "Connection moves whole subtree without data loss");
            graph.Undo(); Check(graph.Document.Text == initial, "Connection is one XML undo"); graph.Redo(); Check(graph.Document.Xml.Descendants("WaitAction").Count() == 2, "Connection redo never duplicates Actions");
            graph.Undo(); graph.Connect("2", "3", "Option"); Check(graph.Document.Element("2/0").Name.LocalName == "Option", "Dialogue port creates an Option");
            graph.Undo(); graph.Connect("1", "3", "next"); Check(graph.Document.Element("2").Attribute("time").Value == "3", "Sequence port inserts after source");
            graph.Undo(); graph.Connect("3", "1", "next"); Check(graph.Document.Element("3").Attribute("time").Value == "2", "Sequence move adjusts indices when target precedes source");
            var cyclic = new EventDocument("<a><b><c/></b></a>"); string stable = cyclic.Text;
            Throws(() => cyclic.Relocate("0", "0/0"), "Cycle rejected"); Check(cyclic.Text == stable, "Failed cycle leaves XML intact");
            var branches = new Workspace(new EventDocument("<ScriptedEvent><CheckMoneyAction><Success><WaitAction time='1'/></Success><Failure><WaitAction time='2'/></Failure></CheckMoneyAction></ScriptedEvent>"));
            branches.Connect("0","0/1/0","Success"); Check(branches.Document.Element("0").Elements("Success").Count()==1 && branches.Document.Element("0/0").Elements().Count()==2, "Existing Success reused when moving between branches");
            branches.Undo(); Check(branches.Document.Element("0/1/0").Attribute("time").Value=="2", "Moving an existing branch child is undoable");
            string branchBefore=branches.Document.Text; Throws(()=>branches.Connect("0","0/0","Success"),"Branch cannot be placed inside itself"); Check(branches.Document.Text==branchBefore,"Failed branch cycle rolls back");
            var namespaced = new Workspace(new EventDocument("<e:ScriptedEvent xmlns:e='urn:test'/>")); namespaced.Add("", "WaitAction"); Check(namespaced.Document.Element("0").Name.NamespaceName == "urn:test", "Adding retains parent XML namespace");
            var draft = new Workspace(new EventDocument("<ScriptedEvent/>")); draft.Add("", "ConversationAction", new NodePosition { X = 200, Y = 100 }, new Dictionary<string,string> { ["text"] = "one\ntwo" });
            draft.Undo(); Check(!draft.Document.Xml.Root.HasElements, "Add with initial attributes is one undo"); draft.Redo(); Check(draft.Document.Element("0").Attribute("text").Value == "one\ntwo", "Add redo retains multiline text");
            var wide = new Workspace(new EventDocument("<ScriptedEvent>" + string.Concat(Enumerable.Range(0, 5000).Select(i => $"<WaitAction name='node{i}' time='1'/>")) + "</ScriptedEvent>"));
            var watch = System.Diagnostics.Stopwatch.StartNew(); Check(wide.Nodes("", out limited).Count == 400 && limited, "Large canvas component count bounded");
            Check(wide.Nodes("node4999", out limited).Any(n => n.Summary == "" && n.Path == "4999") && !limited, "Search finds late nodes beyond render limit");
            string appended = wide.Add("", "SpawnAction"); Check(wide.Nodes("", out limited).Any(n => n.Path == appended) && limited, "Selected new node remains visible beyond canvas cap");
            wide.Undo(); wide.Redo(); Check(wide.Selected == appended, "Redo restores inserted node selection");
            Console.WriteLine("5,000-node bounded canvas query: " + watch.ElapsedMilliseconds + " ms");
            var playback = new FlowPreview(); var flow = XElement.Parse("<ScriptedEvent><CheckMoneyAction><Success><MoneyAction amount='5'/></Success><Failure><WaitAction time='2'/></Failure></CheckMoneyAction><TriggerEventAction identifier='other'/></ScriptedEvent>"); playback.Start(flow); Check(playback.Current.Name.LocalName == "CheckMoneyAction" && playback.Choices.Count() == 2, "General Action flow offers condition branches");
            playback.Advance(playback.Choices.Last()); Check(playback.Current.Name.LocalName == "WaitAction", "Manual failure walkthrough"); playback.Advance(); Check(playback.Current.Name.LocalName == "TriggerEventAction", "Walkthrough resumes event sequence"); playback.Advance(); Check(playback.Current == null, "Walkthrough ends without executing effects");
            checks += LocalizationTests.Run(scratch);
            checks += CanvasDraftTests.Run(scratch);
            int legacy = CoreTests.Main(new[] { Path.Combine(scratch,"xml-regressions"), args[2], args[3] }); Check(legacy == 0, "Existing XML regression suite passed");
            Console.WriteLine("PASS: " + checks + " standalone checks plus 671 XML checks"); return 0;
        }
        catch(Exception e) { Console.Error.WriteLine(e); return 1; }
    }
}
