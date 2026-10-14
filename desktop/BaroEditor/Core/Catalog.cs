using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace BaroEditor
{
    public sealed class PropertySpec
    {
        public string Name { get; set; }
        public string Type { get; set; }
        [JsonPropertyName("default")] public string Default { get; set; }
        public string[] Choices { get; set; } = Array.Empty<string>();
    }
    public sealed class ActionSpec
    {
        public string Name { get; set; }
        public PropertySpec[] Properties { get; set; } = Array.Empty<PropertySpec>();
        [JsonIgnore] public string Label => EditorText.Node(Name);
        [JsonIgnore] public string Category => Name == "ConversationAction" || Name.Contains("Say") || Name.Contains("Message") ? "对话与界面" :
            Name.StartsWith("Check") || Name is "RNGAction" or "SkillCheckAction" or "GoTo" or "Label" ? "条件与流程" :
            Name.Contains("NPC") || Name is "CombatAction" or "AfflictionAction" or "GodModeAction" or "GiveExpAction" or "GiveSkillExpAction" ? "角色与行为" :
            Name.Contains("Item") || Name.Contains("Spawn") || Name.Contains("Money") || Name.Contains("Price") ? "物品与经济" : "世界与事件";
    }
    public sealed class Catalog
    {
        public string GameVersion { get; set; }
        public ActionSpec[] Actions { get; set; }
        public static Catalog Load(string file)
        {
            var result = JsonSerializer.Deserialize<Catalog>(File.ReadAllText(file), new JsonSerializerOptions { PropertyNameCaseInsensitive = true });
            if (result.Actions == null || result.Actions.Length > 512) throw new InvalidDataException("动作目录无效。");
            return result;
        }
        public PropertySpec[] Properties(string name) => Actions.FirstOrDefault(a => a.Name.Equals(name, StringComparison.OrdinalIgnoreCase))?.Properties ?? Array.Empty<PropertySpec>();
        public IEnumerable<ActionSpec> All => Actions.Concat(new[] { "Option", "Success", "Failure", "Interrupt", "StatusEffect", "Conditional", "Text", "ScriptedEvent", "EventSet", "Label", "GoTo" }.Where(n => !Actions.Any(a => a.Name == n)).Select(n => new ActionSpec { Name = n }));
        private static readonly HashSet<string> containers = new(new[] { "ScriptedEvent", "TraitorEvent", "EventSet", "EventPrefabs", "Option", "Success", "Failure", "Interrupt", "StatusEffect", "Conditional", "Text" }, StringComparer.OrdinalIgnoreCase);
        public static bool IsContainer(string name) => containers.Contains(name);
    }
}
