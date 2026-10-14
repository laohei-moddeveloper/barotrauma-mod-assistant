using System;
using System.Collections.Generic;
using System.Linq;
using System.Xml.Linq;

namespace BaroEditor
{
    // Local walkthrough only. Conditions and gameplay effects are never executed.
    public sealed class FlowPreview
    {
        private sealed class Frame { public XElement[] Nodes; public int Index; }
        private readonly Stack<Frame> stack = new();
        public XElement Current { get; private set; }
        public List<string> Route { get; } = new();
        public bool Limited { get; private set; }
        public void Start(XElement root)
        {
            stack.Clear(); Route.Clear(); Limited = false;
            stack.Push(new Frame { Nodes = Catalog.IsContainer(root.Name.LocalName) ? root.Elements().ToArray() : new[] { root } }); Advance();
        }
        public void Advance(XElement branch = null)
        {
            if (Route.Count >= 256) { Current = null; Limited = true; return; }
            if (branch != null)
            {
                if (EventDocument.Attribute(branch, "endconversation").Equals("true", StringComparison.OrdinalIgnoreCase)) { Current = null; stack.Clear(); return; }
                stack.Push(new Frame { Nodes = branch.Elements().ToArray() });
            }
            Current = null;
            while (stack.Count > 0)
            {
                var frame = stack.Peek(); if (frame.Index >= frame.Nodes.Length) { stack.Pop(); continue; }
                var node = frame.Nodes[frame.Index++];
                if (Catalog.IsContainer(node.Name.LocalName)) { stack.Push(new Frame { Nodes = node.Elements().ToArray() }); continue; }
                Current = node; Route.Add(EditorText.Node(node.Name.LocalName)); return;
            }
        }
        public IEnumerable<XElement> Choices => Current?.Elements().Where(e => e.Name.LocalName is "Option" or "Success" or "Failure" or "Interrupt") ?? Enumerable.Empty<XElement>();
    }
}
