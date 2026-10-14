using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;

namespace BaroEditor
{
    public sealed class EventSearch
    {
        private readonly List<(string Path, string Text)> entries = new();
        public EventSearch(XElement root)
        {
            var pending = new Stack<(XElement Node, string Path)>(); pending.Push((root, ""));
            while (pending.Count > 0)
            {
                var entry = pending.Pop();
                string text = entry.Node.Name.LocalName + " " + EditorText.Node(entry.Node.Name.LocalName) + " " +
                    string.Join(" ", entry.Node.Attributes().Where(a => !a.IsNamespaceDeclaration).Select(a => a.Name.LocalName + " " + EditorText.Property(a.Name.LocalName) + " " + a.Value)) + " " +
                    string.Join(" ", entry.Node.Nodes().OfType<XText>().Where(t => !string.IsNullOrWhiteSpace(t.Value)).Select(t => t.Value));
                entries.Add((entry.Path, text));
                var children = entry.Node.Elements().ToArray();
                for (int i = children.Length - 1; i >= 0; i--) pending.Push((children[i], entry.Path.Length == 0 ? i.ToString() : entry.Path + "/" + i));
            }
        }
        public HashSet<string> Find(string query, string scope, out int count, out bool truncated, int limit = 300)
        {
            var visible = new HashSet<string>(); count = 0; truncated = false;
            foreach (var entry in entries)
            {
                if (scope.Length > 0 && entry.Path != scope && !entry.Path.StartsWith(scope + "/", StringComparison.Ordinal)) continue;
                if (!EditorText.Matches(entry.Text, query)) continue;
                if (++count > limit) { truncated = true; count--; break; }
                string path = entry.Path;
                while (true)
                {
                    visible.Add(path);
                    if (path == scope || path.Length == 0) break;
                    int last = path.LastIndexOf('/'); path = last < 0 ? "" : path[..last];
                }
            }
            return visible;
        }
    }
}
