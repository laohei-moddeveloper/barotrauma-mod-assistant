using System;
using System.Linq;
using System.Threading.Tasks;
using System.Windows.Controls;
using Microsoft.Win32;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private bool importingLocalization;
        private void ShowLocalization()
        {
            var menu = new ContextMenu { Background = panel, Foreground = ink };
            var import = new MenuItem { Header = importingLocalization ? "正在导入…" : "导入本地化 XML（可多选）", IsEnabled = !importingLocalization };
            import.Click += (_, _) => ImportLocalization(); menu.Items.Add(import);
            foreach (string language in Model.Localization.Languages.OrderBy(l => l))
            {
                var item = new MenuItem { Header = language, IsCheckable = true, IsChecked = language == Model.Localization.Language, IsEnabled = !importingLocalization };
                item.Click += (_, _) => Safe(() => { CommitInspector(); Model.Localization.Select(language); RefreshAll(); if (inspectorMode == "preview") RefreshPreview(); SetStatus("预览语言：" + language + " · " + Model.Localization.Count + " 个词条 · XML 标签保留"); }); menu.Items.Add(item);
            }
            var clear = new MenuItem { Header = "清除导入的本地化", IsEnabled = !importingLocalization && Model.Localization.Languages.Any() };
            clear.Click += (_, _) => Safe(() => { CommitInspector(); Model.Localization.Clear(); RefreshAll(); if (inspectorMode == "preview") RefreshPreview(); }); menu.Items.Add(clear);
            menu.PlacementTarget = this; menu.IsOpen = true;
        }
        private async void ImportLocalization()
        {
            if (importingLocalization) return;
            var dialog = new OpenFileDialog { Title = "选择原版或模组的本地化 XML（infotexts，可多选）", Filter = "本地化 XML|*.xml", Multiselect = true, CheckFileExists = true };
            if (dialog.ShowDialog(this) != true) return;
            var workspace = Model; var imported = new Localization(); imported.Restore(workspace.Localization.Snapshot());
            importingLocalization = true; SetStatus("正在读取本地化…");
            try
            {
                await Task.Run(() => imported.Import(dialog.FileNames));
                if (!ReferenceEquals(workspace, Model)) return;
                CommitInspector(); Model.Localization.Restore(imported.Snapshot()); RefreshAll(); if (inspectorMode == "preview") RefreshPreview();
                SetStatus("已导入 " + dialog.FileNames.Length + " 个文件 · " + Model.Localization.Language + " · " + Model.Localization.Count + " 个词条 · 原文标签保留，工程保存译文");
            }
            catch (Exception e) { SetStatus("本地化导入未完成：" + e.Message, true); }
            finally { importingLocalization = false; }
        }
    }
}
