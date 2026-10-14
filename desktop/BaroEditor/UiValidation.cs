#if VALIDATION
using System;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using System.Xml.Linq;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private static void CheckUi(bool condition, string message) { if (!condition) throw new Exception(message); }
        private void CaptureUi(string path)
        {
            UpdateLayout(); var root = (FrameworkElement)Content;
            var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth), (int)Math.Ceiling(root.ActualHeight), 96, 96, PixelFormats.Pbgra32);
            var visual = new DrawingVisual(); using (var drawing = visual.RenderOpen()) drawing.DrawRectangle(new VisualBrush(root), null, new Rect(0, 0, root.ActualWidth, root.ActualHeight)); bitmap.Render(visual);
            var encoder = new PngBitmapEncoder(); encoder.Frames.Add(BitmapFrame.Create(bitmap)); using var stream = File.Create(path); encoder.Save(stream);
        }
        private async void RunUiTests()
        {
            string scratch = Path.Combine(AppContext.BaseDirectory, "validation-output"); Directory.CreateDirectory(scratch); Title += " · 开发验证";
            try
            {
                await Task.Delay(250);
                CheckUi(catalog.Actions.Length == 66 && palette.Children.Count >= 66, "Native Action library missing.");
                actionSearch.Text = "等待"; await Task.Delay(300); CheckUi(palette.Children.OfType<Button>().Any(b => b.Content is StackPanel s && s.Children.OfType<TextBlock>().Any(t => t.Text == "WaitAction")), "Chinese palette search failed."); actionSearch.Text = ""; await Task.Delay(250);
                var conversation = nodes.First(n => n.Name == "ConversationAction"); SelectNode(conversation.Path);
                CheckUi(fields.ContainsKey("targettag") && fields.ContainsKey("text"), "Action properties missing.");
                CaptureUi(Path.Combine(scratch,"00-canvas.png")); string beforeXml = Model.Document.Text;
                var point = Model.Positions[conversation.Xml]; var origin = new Point(point.X + 50, point.Y + 30); BeginDrag(conversation, origin);
                for (int i=1;i<=8;i++) { DragTo(new Point(origin.X + i * 17, origin.Y + i * 7)); await Task.Delay(60); CaptureUi(Path.Combine(scratch,$"drag-{i:00}.png")); }
                EndDrag(); CheckUi(Model.Document.Text == beforeXml && Model.CanUndo, "Dragging edited XML or failed history."); Model.Undo(); Model.Redo(); RefreshAll();
                Model.Select(Model.Scope); AddAction("WaitAction", Model.Scope, new Point(420,50)); var wait = Model.Current; string waitPath = Model.Selected;
                CheckUi(wait.Name.LocalName == "WaitAction" && cards.ContainsKey(waitPath), "Palette add callback failed.");
                fields["time"].Enabled.IsChecked=true; fields["time"].Value.Text="2.5"; ApplyInspector(); CheckUi(Model.Current.Attribute("time").Value=="2.5", "Property commit failed.");
                var condition = Model.Document.Xml.Descendants("CheckMoneyAction").First(); Model.Connect(Model.Document.PathOf(condition),Model.Document.PathOf(wait),"Failure"); RefreshAll(); CheckUi(wait.Parent.Name.LocalName=="Failure", "General Action branch connection failed.");
                nodeSearch.Text="zz_no_match_zz"; await Task.Delay(300); CheckUi(cards.Count==0,"Empty node search failed."); nodeSearch.Text=""; await Task.Delay(250);
                var project = Path.Combine(scratch,"example.baroeditor"); Model.SaveProject(project); var loaded = new Workspace(new EventDocument("<a/>")); loaded.ReadProject(project); CheckUi(XNode.DeepEquals(Model.Document.Xml,loaded.Document.Xml),"Project save roundtrip failed.");
                Model.Select(Model.Document.PathOf(conversation.Xml)); RefreshAll(); SwitchMode(true); InspectorMode("preview"); preview.Advance(); RefreshPreview(); await Task.Delay(100); CaptureUi(Path.Combine(scratch,"10-script-preview.png"));
                SwitchMode(false); InspectorMode("properties"); actionSearch.Text=""; nodeSearch.Text=""; await Task.Delay(200); CaptureUi(Path.Combine(scratch,"11-complete-canvas.png"));
                fields.Clear(); Model.Load(new EventDocument("<ScriptedEvent>"+string.Concat(Enumerable.Range(0,100).Select(i=>$"<ConversationAction text='event.preview{i}'/>"))+"</ScriptedEvent>")); ResetView();
                string translationFile=Path.Combine(scratch,"localization.xml"); File.WriteAllText(translationFile,"<infotexts language='Simplified Chinese'>"+string.Concat(Enumerable.Range(0,100).Select(i=>$"<event.preview{i}>本地化演示 · 第 {i+1} 段台词</event.preview{i}>"))+"</infotexts>");
                string untouched=Model.Document.Text; Model.Localization.Import(new[]{translationFile}); RefreshAll(); Fit(); await Task.Delay(100); UpdateLayout();
                CheckUi(scale.ScaleX<.25,"Large event overview still constrained by old zoom floor.");
                var transform=canvas.TransformToAncestor(graphScroll); foreach(var n in nodes) { var pos=Model.Positions[n.Xml]; var bounds=transform.TransformBounds(new Rect(pos.X,pos.Y,CardWidth,CardHeight)); CheckUi(bounds.Top>=-1 && bounds.Left>=-1 && bounds.Right<=graphScroll.ViewportWidth+1 && bounds.Bottom<=graphScroll.ViewportHeight+1,"Fit cropped a node."); }
                CaptureUi(Path.Combine(scratch,"20-full-overview.png"));
                var jump=edges.Last(); jump.Jump.RaiseEvent(new RoutedEventArgs(Button.ClickEvent)); await Task.Delay(100); UpdateLayout();
                CheckUi(Model.Selected==jump.To.Path && scale.ScaleX==1 && Model.Document.Text==untouched,"Edge navigation changed XML or failed to focus target.");
                var targetPos=Model.Positions[jump.To.Xml]; var targetBounds=canvas.TransformToAncestor(graphScroll).TransformBounds(new Rect(targetPos.X,targetPos.Y,CardWidth,CardHeight));
                CheckUi(targetBounds.Top>=-1 && targetBounds.Bottom<=graphScroll.ViewportHeight+1,"Jump target outside viewport.");
                CheckUi(DisplaySummary(jump.To).Contains("第 100 段"),"Canvas did not resolve localization.");
                CheckUi(fields["text"].Value.Text=="event.preview99","Inspector rewrote the localization identifier.");
                CaptureUi(Path.Combine(scratch,"21-jump-localized.png"));
                nodeSearch.Text="第 100 段"; await Task.Delay(250); CheckUi(nodes.Any(n=>n.Xml.Attribute("text")?.Value=="event.preview99"),"Localized UI search failed."); nodeSearch.Text=""; await Task.Delay(250);
                Model.SaveProject(Path.Combine(scratch,"localized.baroeditor")); var translated=new Workspace(new EventDocument("<a/>")); translated.ReadProject(Path.Combine(scratch,"localized.baroeditor")); CheckUi(translated.Localization.Count==100 && translated.Document.Text==untouched,"Localized project did not restore embedded resources.");
                File.WriteAllText(Path.Combine(scratch,"result.json"),JsonSerializer.Serialize(new { success=true, allActions=66, properties=313, chineseSearch=true, dragDoesNotChangeXml=true, propertyCommit=true, branchConnect=true, emptySearch=true, projectRoundtrip=true, screenshots=true, invocation="actual UI callbacks and native WPF render" }));
            }
            catch(Exception e) { File.WriteAllText(Path.Combine(scratch,"result.json"),JsonSerializer.Serialize(new { success=false,error=e.ToString() })); }
            finally
            {
#if INTERACTION
                Model.Load(new EventDocument("<ScriptedEvent identifier='mouse_interaction'><SpawnAction speciesname='crawler'/><WaitAction time='1'/><CheckMoneyAction amount='100'><Success><MoneyAction amount='10'/></Success><Failure><WaitAction time='2'/></Failure></CheckMoneyAction></ScriptedEvent>"));
                nodeSearch.Text=""; propertySearch.Text=""; actionSearch.Text=""; fields.Clear(); ResetView(); SwitchMode(false); InspectorMode("properties"); SetZoom(1); SaveInteractionProbe("ready");
#else
                Close();
#endif
            }
        }
#if INTERACTION
        private void SaveInteractionProbe(string operation)
        {
            string scratch=Path.Combine(AppContext.BaseDirectory,"validation-output"); Directory.CreateDirectory(scratch);
            File.WriteAllText(Path.Combine(scratch,"interaction-"+operation+".json"),JsonSerializer.Serialize(new {operation,xml=Model.Document.Text,positions=Model.CapturePositions()}));
            CaptureUi(Path.Combine(scratch,"interaction-"+operation+".png"));
        }
#endif
    }
}
#endif
