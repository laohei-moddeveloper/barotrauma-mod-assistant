using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;

namespace BaroEditor
{
    public static class EventStructure
    {
        public static bool IsEvent(XElement node) => node.Name.LocalName is "ScriptedEvent" or "TraitorEvent";
        public static bool IsDefinition(string name) => name is "ScriptedEvent" or "TraitorEvent" or "EventSet";
        public static void RequirePlacement(XElement parent, IEnumerable<XElement> moving)
        {
            bool insideEvent=parent.AncestorsAndSelf().Any(IsEvent);
            foreach(var root in moving)
            {
                if(insideEvent && root.DescendantsAndSelf().Any(n=>IsDefinition(n.Name.LocalName)))
                    throw new InvalidDataException("事件组（EventSet）和脚本事件（ScriptedEvent/TraitorEvent）不能嵌套在事件内部。请选择事件文件的合适顶层位置。");
                if(Violations(root).Any()) throw new InvalidDataException("此子树包含嵌套在事件内部的事件组或脚本事件。请先修正结构。");
            }
        }
        public static IEnumerable<XElement> Violations(XElement root) => root.DescendantsAndSelf().Where(n=>IsDefinition(n.Name.LocalName) && n.Ancestors().Any(IsEvent));
    }
}
