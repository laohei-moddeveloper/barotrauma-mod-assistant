using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using BaroEditor;

internal static class CoreTests
{
    private static int passed;
    private static void Check(bool condition, string message) { if (!condition) throw new Exception(message); passed++; }
    private static void Throws(Action action, string message) { try { action(); } catch { passed++; return; } throw new Exception(message); }
    public static int Main(string[] args)
    {
        try
        {
            string directory = Path.GetFullPath(args[0]); Directory.CreateDirectory(directory);
            const string original = "<EventPrefabs><!--keep--><ScriptedEvent identifier='a' commonness='7'><UnknownAction private='keep'><Success><ConversationAction Text='start' custom='x'><Interrupt><WaitAction time='3'/></Interrupt><Option text='next'><ConversationAction text='question' custom='y'><Option text='yes'><GiveMoneyAction amount='15'/></Option><Option text='no' endconversation='true'/></ConversationAction></Option></ConversationAction></Success><Failure><GoTo name='finish'/></Failure></UnknownAction><Label name='finish'/></ScriptedEvent><ScriptedEvent identifier='b'><WaitAction time='2'/></ScriptedEvent></EventPrefabs>";
            var d = new EventDocument(original);
            Check(d.EventPaths().Count == 2, "Events in a container");
            Check(d.Text.Contains("<!--keep-->") && d.Text.Contains("private=\"keep\""), "Unknown nodes and comments retained");
            string conversation = d.PathOf(d.Xml.Descendants("ConversationAction").First());
            Check(d.ConversationLines(conversation).SequenceEqual(new[] { "start", "question" }), "Nested conversation read");
            d.SetConversationLines(conversation, new[] { "one", "two", "three" });
            Check(d.ConversationLines(conversation).Count == 3, "Batch expansion");
            Check(d.Element(conversation).Element("Interrupt") != null, "Root interrupt retained");
            Check(d.Element(conversation).Descendants("GiveMoneyAction").Count() == 1, "Terminal action retained exactly once");
            Check(d.Element(conversation).Descendants("Option").Single(e => (string)e.Attribute("text") == "no").Attribute("endconversation").Value == "true", "Ending option retained");
            Check(d.Element(conversation).Descendants("ConversationAction").All(e => e.Attribute("custom") != null), "Per-line custom attributes retained");
            Throws(() => d.SetConversationLines(conversation, new[] { "shortened" }), "Silent deletion in batch must be refused");
            string after = d.Text; d.Undo(); Check(d.Text.Contains("text=\"question\""), "Undo restores original nested tree"); d.Redo(); Check(d.Text == after, "Redo exact XML");
            string wait = d.PathOf(d.Xml.Descendants("WaitAction").Last());
            d.SetAttributes(wait, new Dictionary<string, string> { ["time"] = "5.5", ["future"] = "α & \"β\"" });
            Check(d.Element(wait).Attribute("time").Value == "5.5", "Attribute edit");
            Check(new EventDocument(d.Text).Element(wait).Attribute("future").Value == "α & \"β\"", "Attribute escaping");
            string stable = d.Text;
            Throws(() => d.SetAttributes(wait, new Dictionary<string, string> { ["ok"] = "1", ["bad name"] = "2" }), "Invalid mutation fails");
            Check(d.Text == stable, "Failed mutation rolls back completely");
            d.Duplicate(wait); Check(d.Xml.Descendants("WaitAction").Count() == 3, "Duplicate selected subtree");
            d.Delete(wait); Check(d.Xml.Descendants("WaitAction").Count() == 2, "Delete selected subtree");
            d.Undo(); Check(d.Xml.Descendants("WaitAction").Count() == 3, "Undo delete");
            var order = new EventDocument("<ScriptedEvent identifier='o'><WaitAction time='1'/><WaitAction time='2'/><WaitAction time='3'/></ScriptedEvent>");
            order.Move("0", 1); Check(order.Xml.Root.Elements().Select(e => e.Attribute("time").Value).SequenceEqual(new[] { "2", "1", "3" }), "Action order move");
            order.Undo(); Check(order.Element("0").Attribute("time").Value == "1", "Undo order");
            var structured = new EventDocument("<ConversationAction><Text tag='a'><Replace tag='x' value='y'/></Text></ConversationAction>");
            Throws(() => structured.SetConversationLines("", new[] { "changed" }), "Structured localized text preserved");
            Throws(() => new EventDocument("<!DOCTYPE a [<!ENTITY x SYSTEM 'file:///C:/secret'>]><a>&x;</a>"), "External entities prohibited");
            Throws(() => new EventDocument(string.Concat(Enumerable.Repeat("<a>", 99)) + string.Concat(Enumerable.Repeat("</a>", 99))), "Depth bounded");
            Throws(() => d.SaveCopy(directory, "../outside.xml"), "Path traversal rejected");
            string output = d.SaveCopy(directory, "copy.xml");
            Check(!d.Dirty && XDocument.Load(output).Descendants("UnknownAction").Any(), "Export keeps unknown actions");
            d.SetAttributes(wait, new Dictionary<string, string> { ["time"] = "9" }); d.SaveCopy(directory, "copy.xml");
            Check(File.Exists(output + ".previous"), "Export replacement has a backup");
            string source = Path.Combine(directory, "source.xml"); File.WriteAllText(source, original);
            var imported = EventDocument.Read(source);
            imported.SetAttributes("0", new Dictionary<string, string> { ["commonness"] = "20" });
            Check(File.ReadAllText(source) == original, "Import and editing do not mutate the source");
            imported.OverwriteSource(Path.Combine(directory, "backups"));
            Check(Directory.EnumerateFiles(Path.Combine(directory, "backups")).Any(p => File.ReadAllText(p) == original), "Original backup exact");
            File.WriteAllText(source, "<external/>");
            Throws(() => imported.OverwriteSource(Path.Combine(directory, "backups")), "External edits block overwriting");
            Check(File.ReadAllText(source) == "<external/>", "External file retained");
            Throws(() => new EventDocument("<a/>").OverwriteSource(directory), "Memory import cannot overwrite anything");
            var interrupts = new EventDocument("<ConversationAction text='first'><Option text='next' custom='keep'><!--transition--><ConversationAction text='last'><Interrupt><GiveMoneyAction amount='99'/></Interrupt><Option text='end' endconversation='true'/></ConversationAction></Option></ConversationAction>");
            interrupts.SetConversationLines("", new[] { "first", "last", "new" });
            Check(interrupts.Xml.Descendants("GiveMoneyAction").Count() == 1, "New lines never duplicate existing interrupt effects");
            Check(interrupts.Text.Contains("<!--transition-->") && interrupts.Text.Contains("custom=\"keep\""), "Transition comments and attributes retained");
            var namespaced = new EventDocument("<e:ScriptedEvent xmlns:e='urn:test' e:custom='old'><e:UnknownAction/></e:ScriptedEvent>");
            namespaced.SetAttributes("", new Dictionary<string, string> { ["{urn:test}custom"] = "new" });
            Check(namespaced.Xml.Root.Attribute(XName.Get("custom", "urn:test")).Value == "new", "Namespaced extension attributes supported");
            Throws(() => new EventDocument("<a>" + new string('x', EventDocument.MaxBytes) + "</a>"), "Size bounded");
            Throws(() => new EventDocument("<a>" + string.Concat(Enumerable.Repeat("<b/>", EventDocument.MaxElements)) + "</a>"), "Element count bounded");
            var wideWatch = System.Diagnostics.Stopwatch.StartNew();
            var wide = new EventDocument("<EventPrefabs>" + string.Concat(Enumerable.Range(0, 10000).Select(i => $"<ScriptedEvent identifier='e{i}'><WaitAction time='1'/></ScriptedEvent>")) + "</EventPrefabs>");
            var widePaths = wide.EventPaths();
            Check(widePaths.Count == 10000 && widePaths[9999] == "9999", "Wide event list uses indexed linear traversal");
            Console.WriteLine($"Synthetic import + list: 10,000 events, {wideWatch.ElapsedMilliseconds} ms");
            var history = new EventDocument("<a value='0'/>");
            for (int i = 1; i <= 40; i++) history.SetAttributes("", new Dictionary<string, string> { ["value"] = i.ToString() });
            int undoCount = 0; while (history.CanUndo) { history.Undo(); undoCount++; }
            Check(undoCount == 24 && history.Xml.Root.Attribute("value").Value == "16", "History has a bounded 24-edit limit");
            if (args.Length > 1)
            {
                int files = 0, events = 0;
                var watch = System.Diagnostics.Stopwatch.StartNew();
                foreach (string file in Directory.EnumerateFiles(args[1], "*.xml", SearchOption.AllDirectories))
                {
                    var game = EventDocument.Read(file);
                    Check(XNode.DeepEquals(XDocument.Load(file, LoadOptions.PreserveWhitespace), game.Xml), "Native whole-file XML equality");
                    var roots = game.EventPaths();
                    foreach (var path in roots) Check(XNode.DeepEquals(game.Element(path), new EventDocument(game.Element(path).ToString(SaveOptions.DisableFormatting)).Xml.Root), "Native event semantic roundtrip");
                    events += roots.Count; files++;
                }
                Console.WriteLine($"Vanilla import: {files} files, {events} event definitions, {watch.ElapsedMilliseconds} ms");
            }
            Console.WriteLine($"PASS: {passed} checks"); return 0;
        }
        catch (Exception ex) { Console.Error.WriteLine(ex); return 1; }
    }
}
