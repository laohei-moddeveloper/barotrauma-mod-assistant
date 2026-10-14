using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml;
using System.Xml.Linq;

namespace BaroEditor
{
    public sealed class LocalizationData
    {
        public string Language { get; set; } = "";
        public Dictionary<string, Dictionary<string, string>> Languages { get; set; } = new();
    }
    // Offline display data only. Never evaluates replacements or changes event identifiers.
    public sealed class Localization
    {
        public const int MaxCharacters = 16 * 1024 * 1024;
        public const int MaxEntries = 100000;
        private Dictionary<string, Dictionary<string, string>> languages = new(StringComparer.OrdinalIgnoreCase);
        public string Language { get; private set; } = "";
        public long Revision { get; private set; }
        public IEnumerable<string> Languages => languages.Keys;
        public int Count => languages.TryGetValue(Language, out var values) ? values.Count : 0;
        public void Select(string language)
        {
            if (!languages.ContainsKey(language)) throw new InvalidDataException("没有导入该语言。");
            if (Language != language) { Language = language; Revision++; }
        }
        public void Clear() { languages.Clear(); Language = ""; Revision++; }
        public LocalizationData Snapshot() => new() { Language = Language, Languages = languages.ToDictionary(p => p.Key, p => new Dictionary<string, string>(p.Value, StringComparer.OrdinalIgnoreCase), StringComparer.OrdinalIgnoreCase) };
        public void Restore(LocalizationData data)
        {
            var result = new Dictionary<string, Dictionary<string, string>>(StringComparer.OrdinalIgnoreCase);
            int characters = 0, entries = 0;
            if (data?.Languages != null)
            {
                if (data.Languages.Count > 64) throw new InvalidDataException("本地化语言超过 64 种。");
                foreach (var language in data.Languages)
                {
                    if (string.IsNullOrWhiteSpace(language.Key) || language.Key.Length > 128 || language.Value == null) throw new InvalidDataException("本地化语言无效。");
                    var values = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
                    foreach (var entry in language.Value)
                    {
                        if (entry.Key.Length == 0 || entry.Key.Length > 512 || entry.Value == null || entry.Value.Length > 65536) throw new InvalidDataException("本地化词条无效。");
                        characters += entry.Key.Length + entry.Value.Length;
                        if (++entries > MaxEntries || characters > MaxCharacters) throw new InvalidDataException("本地化数据超过预算。");
                        values[entry.Key] = entry.Value;
                    }
                    result[language.Key] = values;
                }
            }
            string selected = data?.Language ?? "";
            if (selected.Length > 128 || selected.Length > 0 && !result.ContainsKey(selected)) throw new InvalidDataException("本地化选中语言无效。");
            languages = result; Language = selected.Length > 0 ? selected : result.Keys.FirstOrDefault() ?? ""; Revision++;
        }
        public void Import(IEnumerable<string> files)
        {
            var paths = files.ToArray(); if (paths.Length == 0 || paths.Length > 64) throw new InvalidDataException("一次请选择 1–64 个本地化 XML 文件。");
            var pending = Snapshot();
            long bytes = 0;
            foreach (string path in paths)
            {
                bytes += new FileInfo(path).Length;
                if (bytes > MaxCharacters * 3L) throw new InvalidDataException("本次导入超过 48 MiB。");
                using var reader = XmlReader.Create(path, new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null, MaxCharactersInDocument = 8 * 1024 * 1024 });
                var root = XDocument.Load(reader).Root;
                if (root == null || !root.Name.LocalName.Equals("infotexts", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("请选择潜渊症 infotexts 本地化文件。");
                string language = EventDocument.Attribute(root, "language");
                if (string.IsNullOrWhiteSpace(language)) throw new InvalidDataException("本地化文件缺少 language 属性。");
                if (!pending.Languages.TryGetValue(language, out var values)) pending.Languages[language] = values = new(StringComparer.OrdinalIgnoreCase);
                // Repeated alternatives in one file: deterministic first entry. Later explicitly imported files override earlier files.
                var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                foreach (var entry in root.Elements()) if (seen.Add(entry.Name.LocalName)) values[entry.Name.LocalName] = entry.Value;
            }
            if (pending.Language.Length == 0) pending.Language = pending.Languages.Keys.FirstOrDefault(k => k.Equals("Simplified Chinese", StringComparison.OrdinalIgnoreCase)) ?? pending.Languages.Keys.First();
            Restore(pending); // Transactional: failures leave the previous catalog intact.
        }
        public string Resolve(string key) => key != null && languages.TryGetValue(Language, out var values) && values.TryGetValue(key, out var text) ? text : key ?? "";
        public string Text(XElement node)
        {
            var structured = node.Elements().FirstOrDefault(e => e.Name.LocalName.Equals("Text", StringComparison.OrdinalIgnoreCase));
            string raw = structured == null ? EventDocument.Attribute(node, "text") : EventDocument.Attribute(structured, "tag");
            string text = Resolve(raw);
            if (structured != null)
            {
                foreach (var replace in structured.Elements().Where(e => e.Name.LocalName.Equals("Replace", StringComparison.OrdinalIgnoreCase)))
                {
                    string tag = EventDocument.Attribute(replace, "tag"), value = EventDocument.Attribute(replace, "value");
                    // Dynamic target values stay as placeholders; only static values have an offline preview.
                    if (tag.Length > 0 && value.Length > 0) text = text.Replace(tag, Resolve(value), StringComparison.Ordinal);
                }
            }
            return text;
        }
        public string SearchText(XElement node) => Text(node) + " " + string.Join(" ", node.Attributes().Where(a => !a.IsNamespaceDeclaration).Select(a => Resolve(a.Value)));
    }
}
