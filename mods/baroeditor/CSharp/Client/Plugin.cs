using System;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using Barotrauma;
using Barotrauma.LuaCs;
using HarmonyLib;
using Microsoft.Xna.Framework;

#pragma warning disable CS0436
[assembly: IgnoresAccessChecksTo("Barotrauma")]
[assembly: IgnoresAccessChecksTo("BarotraumaCore")]
#pragma warning restore CS0436
namespace System.Runtime.CompilerServices
{
    [AttributeUsage(AttributeTargets.Assembly, AllowMultiple = true)]
    internal sealed class IgnoresAccessChecksToAttribute : Attribute
    {
        public string AssemblyName { get; }
        public IgnoresAccessChecksToAttribute(string name) { AssemblyName = name; }
    }
}
namespace BaroEditor
{
    public sealed class Plugin : IAssemblyPlugin
    {
        private Harmony harmony;
        private DebugConsole.Command command;
        internal static GUIButton Entry;
        public void Initialize() { harmony = new Harmony("laohei.baroeditor.editor.0.1"); }
        public void PreInitPatching() { }
        public void OnLoadCompleted()
        {
            harmony.UnpatchSelf();
            harmony.PatchAll(typeof(EditorCreation));
            harmony.PatchAll(typeof(EditorGui));
            harmony.PatchAll(typeof(EditorInput));
            if (command != null) DebugConsole.commands.Remove(command);
            command = new DebugConsole.Command("baroeditor|beditor|barodialogue|bdialogue", "Open BaroEditor in the event editor.", _ => Open(), null, false);
            DebugConsole.commands.Add(command);
            if (GameMain.EventEditorScreen != null) Attach(GameMain.EventEditorScreen);
            LuaCsLogger.LogMessage("[BaroEditor] Loaded. F3: baroeditor. Editor-only; no runtime action patches or networking.");
        }
        internal static void Open()
        {
            if (Screen.Selected != GameMain.MainMenuScreen && Screen.Selected != GameMain.EventEditorScreen)
            {
                DebugConsole.NewMessage(Editor.T("请先返回主菜单，再打开事件编辑器。", "Return to the main menu before opening the event editor."), Color.Yellow);
                return;
            }
            if (Screen.Selected != GameMain.EventEditorScreen) GameMain.EventEditorScreen.Select();
            DebugConsole.isOpen = false;
            GUI.KeyboardDispatcher.Subscriber = null;
            Editor.Open();
        }
        private static void Attach(EventEditorScreen screen)
        {
            Entry = new GUIButton(new RectTransform(new Vector2(0.17f, 0.048f), GUI.Canvas, Anchor.TopRight)
                { AbsoluteOffset = new Point(-18, 16), MinSize = new Point(200, 34) }, "BaroEditor");
            Entry.OnClicked = (_, _) => { Editor.Open(); return true; };
        }
        public void Dispose()
        {
            harmony?.UnpatchSelf();
            if (command != null) DebugConsole.commands.Remove(command);
            Editor.Close(); Entry = null; ActionCatalog.Reset();
        }
        [HarmonyPatch(typeof(EventEditorScreen), "CreateGUI")]
        private static class EditorCreation { private static void Postfix(EventEditorScreen __instance) => Attach(__instance); }
        [HarmonyPatch(typeof(EventEditorScreen), "AddToGUIUpdateList")]
        private static class EditorGui
        {
            private static bool Prefix() { if (!Editor.IsOpen) return true; Editor.AddToGUIUpdateList(); return false; }
            private static void Postfix() { if (!Editor.IsOpen) Entry?.AddToGUIUpdateList(); }
        }
        [HarmonyPatch(typeof(EventEditorScreen), "Update")]
        private static class EditorInput { private static bool Prefix() => !Editor.IsOpen; }
    }

    internal sealed class PropertyHint
    {
        public string Name;
        public string Default;
        public Type Type;
    }
    internal static class ActionCatalog
    {
        private static Dictionary<string, Type> actions;
        private static readonly Dictionary<string, PropertyHint[]> properties = new(StringComparer.OrdinalIgnoreCase);
        internal static IReadOnlyDictionary<string, Type> Actions
        {
            get
            {
                if (actions == null)
                    actions = typeof(EventAction).Assembly.GetTypes()
                        .Where(t => !t.IsAbstract && typeof(EventAction).IsAssignableFrom(t))
                        .OrderBy(t => t.Name).ToDictionary(t => t.Name, t => t, StringComparer.OrdinalIgnoreCase);
                return actions;
            }
        }
        internal static PropertyHint[] Properties(string name)
        {
            if (properties.TryGetValue(name, out var cached)) return cached;
            if (!Actions.TryGetValue(name, out var type)) return Array.Empty<PropertyHint>();
            var result = new List<PropertyHint>();
            foreach (PropertyInfo p in type.GetProperties(BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance))
            {
                var attribute = p.GetCustomAttributesData().FirstOrDefault(a => a.AttributeType.FullName == "Barotrauma.Serialize");
                if (attribute == null) continue;
                object value = attribute.ConstructorArguments.FirstOrDefault().Value;
                if (value is CustomAttributeTypedArgument boxed) value = boxed.Value;
                if (p.PropertyType.IsEnum && value != null) value = Enum.ToObject(p.PropertyType, value);
                result.Add(new PropertyHint { Name = p.Name.ToLowerInvariant(), Type = p.PropertyType,
                    Default = value is bool boolean ? boolean.ToString().ToLowerInvariant() : Convert.ToString(value, System.Globalization.CultureInfo.InvariantCulture) ?? "" });
            }
            return properties[name] = result.OrderBy(p => p.Name).ToArray();
        }
        internal static void Reset() { actions = null; properties.Clear(); }
    }
}
