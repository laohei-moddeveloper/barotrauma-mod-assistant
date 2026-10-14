// Development-only harness. Never included in a Workshop or release package.
using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using Barotrauma;
using Barotrauma.LuaCs;
using HarmonyLib;
using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;

namespace BaroEditor
{
    public sealed class GameValidation : IAssemblyPlugin
    {
        private Harmony harmony;
        private static int frame, stage;
        private static string ResultPath => Path.Combine(Directory.GetCurrentDirectory(), "baroeditor-game-test.json");
        public void Initialize() { harmony = new Harmony("baroeditor.validation.only"); }
        public void PreInitPatching() { }
        public void OnLoadCompleted()
        {
            harmony.Patch(AccessTools.Method(typeof(GameMain), "Update", new[] { typeof(GameTime) }), postfix: new HarmonyMethod(typeof(GameValidation), nameof(AfterUpdate)));
        }
        public void Dispose() { harmony?.UnpatchSelf(); }
        private static void Capture(string name)
        {
            var device = GameMain.Instance.GraphicsDevice;
            int width = device.PresentationParameters.BackBufferWidth, height = device.PresentationParameters.BackBufferHeight;
            var pixels = new Color[width * height]; device.GetBackBufferData(pixels);
            using var texture = new Texture2D(device, width, height);
            texture.SetData(pixels);
            using var output = File.Create(Path.Combine(Directory.GetCurrentDirectory(), name));
            texture.SaveAsPng(output, width, height);
        }
        private static void AfterUpdate()
        {
            if (stage == 99 || GameMain.EventEditorScreen == null || GameMain.MainMenuScreen == null) return;
            try
            {
                if (stage == 0)
                {
                    if (Screen.Selected != GameMain.MainMenuScreen || ++frame < 45) return;
                    Plugin.Open();
                    if (!Editor.IsOpen) throw new Exception("Editor window did not open.");
                    stage = 1; frame = 0;
                }
                else if (stage == 1 && ++frame == 12)
                {
                    var methods = typeof(Editor).GetMethods(System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
                    typeof(Editor).GetField("selected", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static).SetValue(null, "0/1");
                    var expansion = (System.Collections.Generic.HashSet<string>)typeof(Editor).GetField("expanded", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static).GetValue(null);
                    expansion.Add("0/1"); expansion.Add("0/1/0");
                    methods.Single(m => m.Name == "RefreshTree").Invoke(null, null);
                    methods.Single(m => m.Name == "RefreshInspector").Invoke(null, null);
                    stage = 3; frame = 0;
                }
                else if (stage == 3 && ++frame == 12)
                {
                    Capture("baroeditor-native-editor.png");
                    var methods = typeof(Editor).GetMethods(System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static);
                    methods.Single(m => m.Name == "BatchDialogue").Invoke(null, null);
                    if (!Editor.DialogOpen) throw new Exception("Dialogue dialog did not open.");
                    var dialog = typeof(Editor).GetField("dialog", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static).GetValue(null);
                    var content = (GUIFrame)dialog.GetType().GetField("Content", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance).GetValue(dialog);
                    var input = content.GetAllChildren<GUITextBox>().Single();
                    if (input.Frame.Rect.Height < 200 || input.Frame.Rect.Height > content.Rect.Height) throw new Exception("Multiline input frame has an invalid height.");
                    stage = 2; frame = 0;
                }
                else if (stage == 2 && ++frame == 12)
                {
                    Capture("baroeditor-native-batch.png");
                    string[] expected = { "ConversationAction", "TagAction", "CheckMoneyAction", "WaitAction", "SpawnAction", "StatusEffectAction", "CheckConditionalAction" };
                    foreach (string name in expected) if (!ActionCatalog.Actions.ContainsKey(name)) throw new Exception("Missing action: " + name);
                    int properties = ActionCatalog.Actions.Keys.Sum(name => ActionCatalog.Properties(name).Length);
                    if (properties < 100 || !ActionCatalog.Properties("ConversationAction").Any(p => p.Name == "targettag")) throw new Exception("Serialized property hints missing.");
                    File.WriteAllText(ResultPath, JsonSerializer.Serialize(new { success = true, version = GameMain.Version.ToString(), actions = ActionCatalog.Actions.Count, serializedProperties = properties, nativeGuiOpened = true, batchGuiOpened = true, runtimePatches = "editor GUI only", validationHarnessExcludedFromRelease = true }));
                    stage = 99; GameMain.Instance.Exit();
                }
            }
            catch (Exception ex)
            {
                File.WriteAllText(ResultPath, JsonSerializer.Serialize(new { success = false, error = ex.ToString() }));
                stage = 99; GameMain.Instance.Exit();
            }
        }
    }
}
