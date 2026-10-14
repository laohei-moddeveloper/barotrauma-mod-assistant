using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Xml;
using System.Xml.Linq;

namespace BaroEditor
{
    // Canonical XML is kept intact. The editor never executes an imported action.
    public sealed class EventDocument
    {
        public const int MaxBytes = 8 * 1024 * 1024;
        public const int MaxElements = 50000;
        public const int MaxDepth = 96;
        public const int HistoryBudget = 8 * 1024 * 1024;
        private sealed class Edit { public string Before; public string After; }
        private readonly List<Edit> undo = new();
        private readonly List<Edit> redo = new();
        private int historyBytes;
        private string savedXml;
        public XDocument Xml { get; private set; }
        public string SourcePath { get; private set; }
        private string sourceHash;
        public bool CanUndo => undo.Count > 0;
        public bool CanRedo => redo.Count > 0;
        public bool Dirty => savedXml != Text;
        public string Text => Xml.ToString(SaveOptions.DisableFormatting);

        public EventDocument(string text) { Xml = Parse(text); savedXml = Text; }
        private EventDocument(XDocument xml) { Xml = xml; savedXml = Text; }
        public static EventDocument Read(string path)
        {
            string absolute = Path.GetFullPath(path);
            var info = new FileInfo(absolute);
            if (!info.Exists || info.Length > MaxBytes) throw new InvalidDataException("XML file is missing or exceeds 8 MiB.");
            byte[] bytes = File.ReadAllBytes(absolute);
            if (bytes.Length > MaxBytes) throw new InvalidDataException("XML file exceeds 8 MiB.");
            using var stream = new MemoryStream(bytes);
            using var reader = XmlReader.Create(stream, ReaderSettings());
            XDocument xml = XDocument.Load(reader, LoadOptions.PreserveWhitespace);
            Validate(xml);
            var result = new EventDocument(xml);
            result.SourcePath = absolute;
            result.sourceHash = Hash(bytes);
            return result;
        }
        private static XmlReaderSettings ReaderSettings() => new()
        {
            DtdProcessing = DtdProcessing.Prohibit,
            XmlResolver = null,
            MaxCharactersInDocument = MaxBytes,
            MaxCharactersFromEntities = 0,
            IgnoreComments = false,
            IgnoreWhitespace = false
        };
        private static XDocument Parse(string text)
        {
            if (string.IsNullOrWhiteSpace(text) || Encoding.UTF8.GetByteCount(text) > MaxBytes)
                throw new InvalidDataException("XML must contain a document of at most 8 MiB.");
            using var reader = XmlReader.Create(new StringReader(text), ReaderSettings());
            XDocument result = XDocument.Load(reader, LoadOptions.PreserveWhitespace);
            Validate(result);
            return result;
        }
        private static void Validate(XDocument xml)
        {
            if (xml.Root == null) throw new InvalidDataException("XML root is missing.");
            var stack = new Stack<(XElement Element, int Depth)>();
            stack.Push((xml.Root, 0));
            int count = 0;
            while (stack.Count > 0)
            {
                var entry = stack.Pop();
                if (++count > MaxElements || entry.Depth > MaxDepth)
                    throw new InvalidDataException("XML exceeds the 50,000-element or 96-level limit.");
                foreach (XElement child in entry.Element.Elements()) stack.Push((child, entry.Depth + 1));
            }
        }
        public XElement Element(string path)
        {
            XElement element = Xml.Root;
            if (string.IsNullOrEmpty(path)) return element;
            foreach (string index in path.Split('/'))
            {
                if (!int.TryParse(index, out int ordinal) || ordinal < 0) throw new InvalidDataException("Invalid XML selection.");
                element = element.Elements().ElementAtOrDefault(ordinal);
                if (element == null) throw new InvalidDataException("The selected node no longer exists.");
            }
            return element;
        }
        public string PathOf(XElement element)
        {
            var parts = new List<int>();
            while (element.Parent != null)
            {
                XElement parent = element.Parent;
                parts.Add(parent.Elements().TakeWhile(e => !ReferenceEquals(e, element)).Count());
                element = parent;
            }
            if (!ReferenceEquals(element, Xml.Root)) throw new InvalidDataException("Node is outside this document.");
            parts.Reverse();
            return string.Join("/", parts);
        }
        public static string Attribute(XElement element, string name) =>
            element.Attributes().FirstOrDefault(a => a.Name.LocalName.Equals(name, StringComparison.OrdinalIgnoreCase))?.Value ?? "";
        public IReadOnlyList<string> EventPaths()
        {
            var result = new List<string>();
            var stack = new Stack<(XElement Node, string Path)>();
            stack.Push((Xml.Root, ""));
            while (stack.Count > 0)
            {
                var entry = stack.Pop();
                if (entry.Node.HasElements && (entry.Node.Name.LocalName.Equals("ScriptedEvent", StringComparison.OrdinalIgnoreCase) ||
                    entry.Node.Name.LocalName.Equals("TraitorEvent", StringComparison.OrdinalIgnoreCase))) result.Add(entry.Path);
                var children = entry.Node.Elements().ToArray();
                for (int i = children.Length - 1; i >= 0; i--)
                    stack.Push((children[i], entry.Path.Length == 0 ? i.ToString() : entry.Path + "/" + i));
            }
            return result;
        }
        private void Change(Action action)
        {
            string before = Text;
            try
            {
                action();
                Validate(Xml);
                string after = Text;
                if (Encoding.UTF8.GetByteCount(after) > MaxBytes) throw new InvalidDataException("Edited XML exceeds 8 MiB.");
                if (before == after) return;
                foreach (Edit edit in redo) historyBytes -= Size(edit);
                redo.Clear();
                var current = new Edit { Before = before, After = after };
                int size = Size(current);
                if (size > HistoryBudget)
                {
                    undo.Clear(); historyBytes = 0;
                }
                else
                {
                    undo.Add(current); historyBytes += size;
                    while (undo.Count > 24 || historyBytes > HistoryBudget)
                    {
                        historyBytes -= Size(undo[0]); undo.RemoveAt(0);
                    }
                }
            }
            catch { Xml = Parse(before); throw; }
        }
        private static int Size(Edit edit) => checked((edit.Before.Length + edit.After.Length) * 2);
        public void SetAttributes(string path, IDictionary<string, string> values)
        {
            Change(() => { XElement node = Element(path); foreach (var pair in values) node.SetAttributeValue(XName.Get(pair.Key), pair.Value); });
        }
        public void RemoveAttribute(string path, string name) => Change(() => Element(path).Attribute(XName.Get(name))?.Remove());
        public void Replace(string path, string xml)
        {
            XElement replacement = Parse(xml).Root;
            Change(() => { if (path.Length == 0) Xml.Root.ReplaceWith(new XElement(replacement)); else Element(path).ReplaceWith(new XElement(replacement)); });
        }
        public void AddChild(string path, string name) => Change(() => Element(path).Add(new XElement(XName.Get(name))));
        public void Duplicate(string path)
        {
            if (path.Length == 0) throw new InvalidDataException("The document root cannot be duplicated.");
            Change(() => { XElement node = Element(path); node.AddAfterSelf(new XElement(node)); });
        }
        public void Delete(string path)
        {
            if (path.Length == 0) throw new InvalidDataException("The document root cannot be deleted.");
            Change(() => Element(path).Remove());
        }
        public void Move(string path, int delta)
        {
            if (path.Length == 0 || (delta != -1 && delta != 1)) return;
            Change(() =>
            {
                XElement node = Element(path), sibling = delta < 0 ? node.ElementsBeforeSelf().LastOrDefault() : node.ElementsAfterSelf().FirstOrDefault();
                if (sibling == null) return;
                node.Remove(); if (delta < 0) sibling.AddBeforeSelf(node); else sibling.AddAfterSelf(node);
            });
        }
        public void Undo()
        {
            if (!CanUndo) return;
            Edit edit = undo[^1]; undo.RemoveAt(undo.Count - 1); redo.Add(edit); Xml = Parse(edit.Before);
        }
        public void Redo()
        {
            if (!CanRedo) return;
            Edit edit = redo[^1]; redo.RemoveAt(redo.Count - 1); undo.Add(edit); Xml = Parse(edit.After);
        }
        public IReadOnlyList<string> ConversationLines(string path)
        {
            return ConversationChain(Element(path)).Select(e => Attribute(e, "text")).ToArray();
        }
        private static List<XElement> ConversationChain(XElement first)
        {
            if (!first.Name.LocalName.Equals("ConversationAction", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Select a ConversationAction first.");
            var result = new List<XElement>();
            XElement current = first;
            while (true)
            {
                if (current.Elements().Any(e => e.Name.LocalName.Equals("Text", StringComparison.OrdinalIgnoreCase)))
                    throw new InvalidDataException("Structured Text elements must be edited in the XML view; batch editing would lose replacements.");
                result.Add(current);
                XElement[] options = current.Elements().Where(e => e.Name.LocalName.Equals("Option", StringComparison.OrdinalIgnoreCase)).ToArray();
                if (options.Length != 1 || Attribute(options[0], "endconversation").Equals("true", StringComparison.OrdinalIgnoreCase)) break;
                XElement[] actions = options[0].Elements().ToArray();
                if (actions.Length != 1 || !actions[0].Name.LocalName.Equals("ConversationAction", StringComparison.OrdinalIgnoreCase)) break;
                current = actions[0];
            }
            return result;
        }
        public void SetConversationLines(string path, IReadOnlyList<string> lines)
        {
            if (lines.Count == 0 || lines.Count > 32 || lines.Any(s => s.Length > 4000))
                throw new InvalidDataException("A batch supports 1–32 lines, at most 4,000 characters per line.");
            var original = ConversationChain(Element(path));
            // Dropping existing lines could discard per-line attributes or interrupt actions.
            // Require an explicit subtree edit for such a change rather than silently losing them.
            if (lines.Count < original.Count) throw new InvalidDataException("To remove existing conversation nodes, use the tree or XML view; batch editing preserves their attributes and interrupts.");
            XElement built = null;
            for (int i = lines.Count - 1; i >= 0; i--)
            {
                XElement template = original[Math.Min(i, original.Count - 1)];
                XElement node = i < original.Count ? new XElement(template) : new XElement(template.Name, template.Attributes());
                foreach (XElement option in node.Elements().Where(e => e.Name.LocalName.Equals("Option", StringComparison.OrdinalIgnoreCase)).ToArray()) option.Remove();
                XAttribute text = node.Attributes().FirstOrDefault(a => a.Name.LocalName.Equals("text", StringComparison.OrdinalIgnoreCase));
                node.SetAttributeValue(text?.Name ?? "text", lines[i]);
                if (i >= original.Count && i > 0 && Attribute(node, "speakertag").Length > 0)
                    node.SetAttributeValue("waitforinteraction", "false");
                if (built == null)
                {
                    foreach (XElement option in original[^1].Elements().Where(e => e.Name.LocalName.Equals("Option", StringComparison.OrdinalIgnoreCase))) node.Add(new XElement(option));
                }
                else
                {
                    XElement option;
                    if (i < original.Count - 1)
                    {
                        option = new XElement(original[i].Elements().First(e => e.Name.LocalName.Equals("Option", StringComparison.OrdinalIgnoreCase)));
                        option.Elements().Single().ReplaceWith(built);
                    }
                    else option = new XElement("Option", new XAttribute("text", "Continue"));
                    if (i >= original.Count - 1) option.Add(built);
                    node.Add(option);
                }
                built = node;
            }
            Replace(path, built.ToString(SaveOptions.DisableFormatting));
        }
        private static string Hash(byte[] bytes) => Convert.ToHexString(SHA256.HashData(bytes));
        public string SaveCopy(string directory, string name)
        {
            if (string.IsNullOrWhiteSpace(name) || name != Path.GetFileName(name) || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 || name.Trim('.') == "")
                throw new InvalidDataException("Use a file name, not a path.");
            string root = Path.GetFullPath(directory); Directory.CreateDirectory(root);
            string target = Path.GetFullPath(Path.Combine(root, name.EndsWith(".xml", StringComparison.OrdinalIgnoreCase) ? name : name + ".xml"));
            if (!target.StartsWith(root.TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Output is outside the selected directory.");
            WriteAtomic(target, Encoding.UTF8.GetBytes(Text), target + ".previous"); savedXml = Text; return target;
        }
        public void OverwriteSource(string backupDirectory)
        {
            if (SourcePath == null) throw new InvalidOperationException("This document was loaded from game memory; export a copy instead.");
            byte[] existing = File.ReadAllBytes(SourcePath);
            if (Hash(existing) != sourceHash) throw new IOException("The source file changed outside BaroEditor. Import it again before overwriting.");
            Directory.CreateDirectory(backupDirectory);
            string backup = Path.Combine(backupDirectory, DateTime.UtcNow.ToString("yyyyMMdd-HHmmss") + "-" + Guid.NewGuid().ToString("N")[..8] + "-" + Path.GetFileName(SourcePath));
            File.WriteAllBytes(backup, existing);
            byte[] output = Encoding.UTF8.GetBytes(Text);
            // The second comparison also detects changes made while the backup was written.
            if (Hash(File.ReadAllBytes(SourcePath)) != sourceHash) throw new IOException("Source changed during backup; no overwrite performed.");
            WriteAtomic(SourcePath, output, null); sourceHash = Hash(output); savedXml = Text;
        }
        private static void WriteAtomic(string target, byte[] bytes, string backup)
        {
            string temporary = target + "." + Guid.NewGuid().ToString("N") + ".tmp";
            try
            {
                using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None)) { stream.Write(bytes); stream.Flush(true); }
                if (File.Exists(target))
                {
                    if (backup != null) File.Copy(target, backup, true);
                    File.Move(temporary, target, true);
                }
                else File.Move(temporary, target);
            }
            finally { if (File.Exists(temporary)) File.Delete(temporary); }
        }
        public static string Example => "<EventPrefabs><ScriptedEvent identifier=\"baroeditor_example\"><TagAction criteria=\"player\" tag=\"player\" /><ConversationAction targettag=\"player\" text=\"Hello, captain.\"><Option text=\"Continue\"><ConversationAction targettag=\"player\" text=\"The pump needs repairs.\"><Option text=\"Accept\"><ConversationAction targettag=\"player\" text=\"Thank you.\" /></Option><Option text=\"Decline\" endconversation=\"true\" /></ConversationAction></Option></ConversationAction></ScriptedEvent></EventPrefabs>";
    }
}
