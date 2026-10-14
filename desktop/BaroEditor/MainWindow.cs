using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Input;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Shapes;
using System.Windows.Threading;
using System.Xml.Linq;
using Microsoft.Win32;
using Path = System.IO.Path;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow : Window
    {
        internal Workspace Model;
        private readonly Catalog catalog;
        private readonly FlowPreview preview = new();
        private readonly Dictionary<string, (CheckBox Enabled, TextBox Value, bool Existed)> fields = new();
        private readonly Dictionary<string, Border> cards = new();
        private readonly List<(GraphNode Node, Border Card)> cardNodes = new();
        private readonly Dictionary<string, DispatcherTimer> delays = new();
        private readonly Brush bg = B("#101C27"), panel = B("#172735"), soft = B("#223F50"), line = B("#354D5D"), accent = B("#A0D5E9"), ink = B("#E0EAF0"), muted = B("#9BB3C2"), amber = B("#DDC396");
        private Canvas canvas;
        private ScrollViewer graphScroll;
        private StackPanel palette, properties, script, playback;
        private TextBox actionSearch, nodeSearch, propertySearch, xmlPreview;
        private TextBlock status, documentLabel, inspectorTitle;
        private ComboBox events, categories;
        private Button undo, redo, graphTab, scriptTab, propertyTab, previewTab, xmlTab;
        private Grid center, inspectorBody;
        private Border graphSurface, scriptSurface;
        private ScrollViewer propertyScroll, previewScroll;
        private Grid xmlSurface;
        private Slider zoom;
        private ScaleTransform scale = new(1, 1);
        private bool building, scriptMode;
        private string projectPath, linkSource, linkKind, inspectorMode = "properties";
        private IReadOnlyList<GraphNode> nodes = Array.Empty<GraphNode>();
        private GraphNode dragging;
        private Point dragOrigin, nodeOrigin;
        private bool didDrag;
        private Dictionary<string, NodePosition> dragBefore;
        private Point? paletteDown, scriptDown;
        private string scriptDragPath;
        private Point? panOrigin;
        private double panX, panY;
        private readonly string[] startupArgs;

        private static SolidColorBrush B(string color) { var result = (SolidColorBrush)new BrushConverter().ConvertFromString(color); result.Freeze(); return result; }
        public MainWindow(string[] args)
        {
            startupArgs = args; Title = "BaroEditor | 潜渊症通用事件编辑器 · 独立版";
            Width = Math.Min(1480, SystemParameters.WorkArea.Width - 32); Height = Math.Min(900, SystemParameters.WorkArea.Height - 32); MinWidth = 1120; MinHeight = 720; WindowStartupLocation = WindowStartupLocation.CenterScreen;
#if VALIDATION
            ShowActivated = false;
#endif
            Background = bg; Foreground = ink; FontFamily = new FontFamily("Microsoft YaHei UI"); FontSize = 13;
            catalog = Catalog.Load(Path.Combine(AppContext.BaseDirectory, "Assets/actions.json"));
            Model = new Workspace(new EventDocument(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets/example.xml"))));
            ApplyStyles(); BuildShell(); RefreshAll();
            Closing += (_, e) => {
#if VALIDATION
                if (startupArgs.Contains("--self-test")) return;
#endif
                CommitInspector(); if (Model.ProjectDirty && !Confirm("草稿有修改。关闭前请保存工程或导出 XML。\n仍然关闭？")) e.Cancel = true;
            };
            PreviewKeyDown += OnKey;
            Loaded += (_, _) =>
            {
                if (args.Length > 0 && args[0] != "--self-test" && File.Exists(args[0])) Safe(() => LoadPath(args[0]));
#if VALIDATION
                if (args.Contains("--self-test")) Dispatcher.BeginInvoke(new Action(RunUiTests), DispatcherPriority.ApplicationIdle);
#endif
            };
        }
        private void ApplyStyles()
        {
            var style = (Style)XamlReader.Parse("<Style xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' TargetType='Button'><Setter Property='Padding' Value='12,7'/><Setter Property='Margin' Value='0,0,8,0'/><Setter Property='Background' Value='#223F50'/><Setter Property='Foreground' Value='#E0EAF0'/><Setter Property='BorderBrush' Value='#354D5D'/><Setter Property='BorderThickness' Value='1'/><Setter Property='Cursor' Value='Hand'/><Setter Property='Template'><Setter.Value><ControlTemplate TargetType='Button'><Border x:Name='surface' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='{TemplateBinding BorderThickness}' CornerRadius='7'><ContentPresenter Margin='{TemplateBinding Padding}' HorizontalAlignment='{TemplateBinding HorizontalContentAlignment}' VerticalAlignment='Center'/></Border><ControlTemplate.Triggers><Trigger Property='IsMouseOver' Value='True'><Setter TargetName='surface' Property='BorderBrush' Value='#A0D5E9'/></Trigger><Trigger Property='IsEnabled' Value='False'><Setter Property='Opacity' Value='.4'/></Trigger></ControlTemplate.Triggers></ControlTemplate></Setter.Value></Setter></Style>");
            Resources.Add(typeof(Button), style);
            var input = new Style(typeof(TextBox)); input.Setters.Add(new Setter(Control.BackgroundProperty, bg)); input.Setters.Add(new Setter(Control.ForegroundProperty, ink)); input.Setters.Add(new Setter(Control.BorderBrushProperty, line)); input.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(10, 8, 10, 8))); input.Setters.Add(new Setter(Control.MinHeightProperty, 36d)); input.Setters.Add(new Setter(TextBoxBase.SelectionBrushProperty, B("#315F76"))); Resources.Add(typeof(TextBox), input);
            input.Setters.Add(new Setter(Control.TemplateProperty, XamlReader.Parse("<ControlTemplate xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' TargetType='TextBox'><Border Background='{TemplateBinding Background}' BorderBrush='{TemplateBinding BorderBrush}' BorderThickness='{TemplateBinding BorderThickness}' CornerRadius='7'><Grid><ScrollViewer x:Name='PART_ContentHost' Margin='{TemplateBinding Padding}'/><TextBlock x:Name='hint' Text='{TemplateBinding Tag}' Foreground='#8099A9' Margin='{TemplateBinding Padding}' Visibility='Collapsed' IsHitTestVisible='False' TextTrimming='CharacterEllipsis'/></Grid></Border><ControlTemplate.Triggers><Trigger Property='Text' Value=''><Setter TargetName='hint' Property='Visibility' Value='Visible'/></Trigger></ControlTemplate.Triggers></ControlTemplate>")));
            var combo = (Style)XamlReader.Parse("<Style xmlns='http://schemas.microsoft.com/winfx/2006/xaml/presentation' xmlns:x='http://schemas.microsoft.com/winfx/2006/xaml' TargetType='ComboBox'><Setter Property='Foreground' Value='#E0EAF0'/><Setter Property='Background' Value='#172735'/><Setter Property='BorderBrush' Value='#354D5D'/><Setter Property='Template'><Setter.Value><ControlTemplate TargetType='ComboBox'><Grid><ToggleButton Foreground='#E0EAF0' IsChecked='{Binding IsDropDownOpen, RelativeSource={RelativeSource TemplatedParent}, Mode=TwoWay}' Focusable='False'><ToggleButton.Template><ControlTemplate TargetType='ToggleButton'><Border Background='#172735' BorderBrush='#354D5D' BorderThickness='1' CornerRadius='7'><DockPanel><TextBlock Text='▾' Foreground='#A0D5E9' DockPanel.Dock='Right' Margin='8,4'/><ContentPresenter Margin='10,6' Content='{Binding SelectionBoxItem, RelativeSource={RelativeSource AncestorType=ComboBox}}' ContentTemplate='{Binding SelectionBoxItemTemplate, RelativeSource={RelativeSource AncestorType=ComboBox}}'/></DockPanel></Border></ControlTemplate></ToggleButton.Template></ToggleButton><Popup x:Name='PART_Popup' IsOpen='{TemplateBinding IsDropDownOpen}' Placement='Bottom' AllowsTransparency='True' Focusable='False'><Border Background='#172735' BorderBrush='#354D5D' BorderThickness='1' CornerRadius='6' MinWidth='{Binding ActualWidth, RelativeSource={RelativeSource TemplatedParent}}'><ScrollViewer MaxHeight='300' CanContentScroll='True'><ItemsPresenter/></ScrollViewer></Border></Popup></Grid></ControlTemplate></Setter.Value></Setter></Style>"); Resources.Add(typeof(ComboBox), combo);
            var itemStyle = new Style(typeof(ComboBoxItem)); itemStyle.Setters.Add(new Setter(Control.ForegroundProperty, ink)); itemStyle.Setters.Add(new Setter(Control.BackgroundProperty, panel)); itemStyle.Setters.Add(new Setter(Control.PaddingProperty, new Thickness(10, 7, 10, 7))); Resources.Add(typeof(ComboBoxItem), itemStyle);
            var tip = new Style(typeof(ToolTip)); tip.Setters.Add(new Setter(Control.BackgroundProperty, soft)); tip.Setters.Add(new Setter(Control.ForegroundProperty, ink)); Resources.Add(typeof(ToolTip), tip);
        }
        private TextBlock Text(string value, double size = 13, Brush color = null, bool bold = false) => new() { Text = value, FontSize = size, Foreground = color ?? ink, TextWrapping = TextWrapping.Wrap, FontWeight = bold ? FontWeights.SemiBold : FontWeights.Normal, VerticalAlignment = VerticalAlignment.Center };
        private Button Btn(string text, Action click, bool primary = false)
        {
            var button = new Button { Content = text, Background = primary ? B("#A0D5E9") : soft, Foreground = primary ? bg : ink, HorizontalContentAlignment = HorizontalAlignment.Center };
            button.Click += (_, _) => Safe(click); return button;
        }
        private Border Box(UIElement content, Thickness? padding = null) => new() { Background = panel, BorderBrush = line, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(10), Padding = padding ?? new Thickness(14), Child = content };
        private static void At(Grid grid, UIElement element, int row = 0, int col = 0) { Grid.SetRow(element, row); Grid.SetColumn(element, col); grid.Children.Add(element); }
        private static Grid Rows(params GridLength[] lengths) { var grid = new Grid(); foreach (var length in lengths) grid.RowDefinitions.Add(new RowDefinition { Height = length }); return grid; }
        private static readonly GridLength Auto = GridLength.Auto, Star = new(1, GridUnitType.Star);
        private TextBox Search(string hint, Action<string> changed, string key)
        {
            var input = new TextBox { ToolTip = hint, Tag = key == "actions" ? "搜索动作 · 中文 / XML 名" : key == "nodes" ? "搜索节点、台词、标识符" : key == "properties" ? "筛选属性 · 中文 / XML 名" : "输入关键词搜索", MaxLength = 256, Margin = new Thickness(0, 6, 0, 10) };
            input.TextChanged += (_, _) => Later(key, () => changed(input.Text)); return input;
        }
        private void Later(string key, Action action)
        {
            if (delays.TryGetValue(key, out var old)) old.Stop();
            var timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(180) };
            timer.Tick += (_, _) => { timer.Stop(); delays.Remove(key); Safe(action); }; delays[key] = timer; timer.Start();
        }
        private void Safe(Action action)
        {
            try { action(); }
            catch (Exception e) { SetStatus("操作未完成：" + e.Message, true); }
        }
        private void SetStatus(string message, bool error = false) { if (status != null) { status.Text = message; status.Foreground = error ? amber : muted; } }
        private bool Confirm(string message) => MessageBox.Show(this, message, "BaroEditor", MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes;
        private void BuildShell()
        {
            var root = Rows(new GridLength(68), new GridLength(52), Star, new GridLength(48)); root.Background = bg; root.Margin = new Thickness(18, 12, 18, 8); Content = root;
            var header = new DockPanel { Margin = new Thickness(0, 0, 0, 10) };
            var commands = new StackPanel { Orientation = Orientation.Horizontal, VerticalAlignment = VerticalAlignment.Center }; DockPanel.SetDock(commands, Dock.Right);
            undo = Btn("↶ 撤销", () => { CommitInspector(); Model.Undo(); RefreshAll(); }); redo = Btn("↷ 重做", () => { Model.Redo(); RefreshAll(); });
            commands.Children.Add(undo); commands.Children.Add(redo); commands.Children.Add(Btn("保存工程", SaveProject)); commands.Children.Add(Btn("导出 XML", ExportXml, true)); header.Children.Add(commands);
            var brand = new StackPanel(); brand.Children.Add(Text("BAROEDITOR", 23, accent, true)); brand.Children.Add(Text("潜渊症通用事件编辑器    /    独立工作台", 12, muted)); header.Children.Add(brand); At(root, header);
            var toolbar = new DockPanel(); var fileActions = new StackPanel { Orientation = Orientation.Horizontal };
            fileActions.Children.Add(Btn("＋ 新建", NewFile)); fileActions.Children.Add(Btn("导入文件", OpenFile)); fileActions.Children.Add(Btn("原版事件文件", OpenVanilla)); fileActions.Children.Add(Btn("更多 ▾", ShowTools)); DockPanel.SetDock(fileActions, Dock.Left); toolbar.Children.Add(fileActions);
            documentLabel = Text("", 12, muted); documentLabel.TextTrimming = TextTrimming.CharacterEllipsis; toolbar.Children.Add(documentLabel); At(root, toolbar, 1);
            var work = new Grid(); work.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(230), MinWidth = 190, MaxWidth = 360 }); work.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) }); work.ColumnDefinitions.Add(new ColumnDefinition { Width = Star, MinWidth = 470 }); work.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(10) }); work.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(330), MinWidth = 280, MaxWidth = 520 }); At(root, work, 2);
            At(work, BuildPalette(), 0, 0); At(work, new GridSplitter { Width = 5, HorizontalAlignment = HorizontalAlignment.Center, Background = line, ResizeBehavior = GridResizeBehavior.PreviousAndNext }, 0, 1);
            At(work, BuildCenter(), 0, 2); At(work, new GridSplitter { Width = 5, HorizontalAlignment = HorizontalAlignment.Center, Background = line, ResizeBehavior = GridResizeBehavior.PreviousAndNext }, 0, 3); At(work, BuildInspector(), 0, 4);
            var footer = new DockPanel { Margin = new Thickness(0, 8, 0, 0) }; var copy = new StackPanel { Orientation = Orientation.Horizontal }; DockPanel.SetDock(copy, Dock.Right); copy.Children.Add(Btn("复制事件 XML", () => CopyXml(false))); copy.Children.Add(Btn("复制完整 XML", () => CopyXml(true))); footer.Children.Add(copy); status = Text("", 12, muted); footer.Children.Add(status); At(root, footer, 3);
        }
        private UIElement BuildPalette()
        {
            var layout = Rows(Auto, Auto, Auto, Star, Auto); At(layout, Text("动作库", 16, ink, true)); actionSearch = Search("搜索中文名或 XML 动作名", _ => RefreshPalette(), "actions"); At(layout, actionSearch, 1);
            categories = new ComboBox { Margin = new Thickness(0, 0, 0, 12), MinHeight = 32, ItemsSource = new[] { "全部动作", "对话与界面", "条件与流程", "角色与行为", "物品与经济", "世界与事件", "分支与容器" }, SelectedIndex = 0 }; categories.SelectionChanged += (_, _) => RefreshPalette(); At(layout, categories, 2);
            palette = new StackPanel(); At(layout, new ScrollViewer { Content = palette, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }, 3);
            At(layout, Text("拖入画布或节点添加\n点击添加到选中位置\n66 个原版动作 · 未知节点保留", 11, muted), 4); return Box(layout);
        }
        private UIElement BuildCenter()
        {
            center = Rows(Auto, Auto, Star);
            var top = new DockPanel { Margin = new Thickness(0, 0, 0, 10) }; var tabs = new StackPanel { Orientation = Orientation.Horizontal }; graphTab = Btn("节点画布", () => SwitchMode(false)); scriptTab = Btn("剧本卡片", () => SwitchMode(true)); tabs.Children.Add(graphTab); tabs.Children.Add(scriptTab); DockPanel.SetDock(tabs, Dock.Left); top.Children.Add(tabs);
            var view = new StackPanel { Orientation = Orientation.Horizontal, HorizontalAlignment = HorizontalAlignment.Right }; view.Children.Add(Btn("整理", Arrange)); view.Children.Add(Btn("适配", Fit)); zoom = new Slider { Minimum = .25, Maximum = 1.8, Value = 1, Width = 90, VerticalAlignment = VerticalAlignment.Center, ToolTip = "画布缩放 · Ctrl + 滚轮" }; zoom.ValueChanged += (_, _) => { scale.ScaleX = scale.ScaleY = zoom.Value; }; view.Children.Add(zoom); top.Children.Add(view); At(center, top);
            var search = Rows(Auto, Auto); events = new ComboBox { MinHeight = 30, DisplayMemberPath = "Caption" }; events.SelectionChanged += (_, _) => { if (!building && events.SelectedItem is EventChoice choice) { CommitInspector(); Model.SetScope(choice.Path); RefreshAll(); } };
            events.ItemsPanel = new ItemsPanelTemplate(new FrameworkElementFactory(typeof(VirtualizingStackPanel))); VirtualizingPanel.SetIsVirtualizing(events, true); ScrollViewer.SetCanContentScroll(events, true);
            var eventRow = new DockPanel(); var eventProps = Btn("事件属性", () => SelectNode(Model.Scope)); eventProps.Margin = new Thickness(8, 0, 0, 0); DockPanel.SetDock(eventProps, Dock.Right); eventRow.Children.Add(eventProps); eventRow.Children.Add(events); At(search, eventRow);
            nodeSearch = Search("搜索节点、台词、标识符、标签；多个关键词用空格分隔", _ => { CommitInspector(); RefreshGraph(); }, "nodes"); At(search, nodeSearch, 1); At(center, search, 1);
            canvas = new Canvas { Background = GridBrush(), Width = 2000, Height = 1400, AllowDrop = true, LayoutTransform = scale, ClipToBounds = true };
            canvas.Drop += CanvasDrop; canvas.DragOver += (_, e) => { e.Effects = e.Data.GetDataPresent("BaroEditor.Action") ? DragDropEffects.Copy : DragDropEffects.None; e.Handled = true; };
            canvas.MouseLeftButtonDown += (_, e) => { if (e.OriginalSource == canvas) { linkSource = null; if (Keyboard.Modifiers.HasFlag(ModifierKeys.Shift)) { panOrigin = e.GetPosition(graphScroll); panX = graphScroll.HorizontalOffset; panY = graphScroll.VerticalOffset; canvas.CaptureMouse(); } SetStatus("拖动节点移动位置；输出圆点连线；Shift + 拖动平移"); } };
            canvas.MouseMove += (_, e) => { if (panOrigin is Point start && e.LeftButton == MouseButtonState.Pressed) { var point = e.GetPosition(graphScroll); graphScroll.ScrollToHorizontalOffset(panX + start.X - point.X); graphScroll.ScrollToVerticalOffset(panY + start.Y - point.Y); } else if (linkSource != null) DrawGhost(e.GetPosition(canvas)); };
            canvas.MouseLeftButtonUp += (_, _) => { if (panOrigin != null) { panOrigin = null; canvas.ReleaseMouseCapture(); } };
            graphScroll = new ScrollViewer { Content = canvas, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
            graphScroll.PreviewMouseWheel += (_, e) => { if (Keyboard.Modifiers.HasFlag(ModifierKeys.Control)) { zoom.Value = Math.Clamp(zoom.Value + (e.Delta > 0 ? .08 : -.08), .25, 1.8); e.Handled = true; } };
            graphSurface = Box(graphScroll, new Thickness(0)); At(center, graphSurface, 2);
            script = new StackPanel { Margin = new Thickness(14) }; scriptSurface = Box(new ScrollViewer { Content = script, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }, new Thickness(0)); scriptSurface.Visibility = Visibility.Collapsed; At(center, scriptSurface, 2);
            return center;
        }
        private Brush GridBrush()
        {
            var group = new DrawingGroup(); group.Children.Add(new GeometryDrawing(bg, null, new RectangleGeometry(new Rect(0, 0, 24, 24)))); group.Children.Add(new GeometryDrawing(line, null, new EllipseGeometry(new Point(1, 1), .7, .7)));
            var brush = new DrawingBrush(group) { TileMode = TileMode.Tile, Viewport = new Rect(0, 0, 24, 24), ViewportUnits = BrushMappingMode.Absolute, Stretch = Stretch.None }; brush.Freeze(); return brush;
        }
        private UIElement BuildInspector()
        {
            var root = Rows(Auto, Auto, Star, Auto); inspectorTitle = Text("节点属性", 16, accent, true); At(root, inspectorTitle);
            var tabs = new StackPanel { Orientation = Orientation.Horizontal, Margin = new Thickness(0, 12, 0, 10) }; propertyTab = Btn("属性", () => InspectorMode("properties")); previewTab = Btn("试播", () => InspectorMode("preview")); xmlTab = Btn("XML", () => InspectorMode("xml")); tabs.Children.Add(propertyTab); tabs.Children.Add(previewTab); tabs.Children.Add(xmlTab); At(root, tabs, 1);
            inspectorBody = new Grid(); At(root, inspectorBody, 2);
            var propertyRoot = Rows(Auto, Star); propertySearch = Search("筛选属性中文名、XML 名或当前值", _ => { CommitInspector(); RefreshInspector(); }, "properties"); At(propertyRoot, propertySearch); properties = new StackPanel(); propertyScroll = new ScrollViewer { Content = properties, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }; At(propertyRoot, propertyScroll, 1); propertyRoot.Name = "PropertyRoot"; inspectorBody.Children.Add(propertyRoot);
            playback = new StackPanel(); previewScroll = new ScrollViewer { Content = playback, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled, Visibility = Visibility.Collapsed }; inspectorBody.Children.Add(previewScroll);
            xmlSurface = Rows(Star, Auto); xmlSurface.Visibility = Visibility.Collapsed; xmlPreview = new TextBox { IsReadOnly = true, AcceptsReturn = true, AcceptsTab = true, TextWrapping = TextWrapping.NoWrap, VerticalScrollBarVisibility = ScrollBarVisibility.Auto, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, FontFamily = new FontFamily("Consolas"), FontSize = 12 }; At(xmlSurface, xmlPreview); At(xmlSurface, Btn("编辑完整子树 XML", EditXml), 1); inspectorBody.Children.Add(xmlSurface);
            var tools = new WrapPanel { Margin = new Thickness(0, 12, 0, 0) }; foreach (var button in new[] { Btn("应用", ApplyInspector, true), Btn("添加属性", AddAttribute), Btn("批量对话", BatchDialogue), Btn("复制节点", Duplicate), Btn("删除", DeleteNode), Btn("↑", () => Move(-1)), Btn("↓", () => Move(1)) }) { button.Margin = new Thickness(0, 0, 6, 6); tools.Children.Add(button); } At(root, tools, 3); return Box(root);
        }
        private void InspectorMode(string mode)
        {
            CommitInspector(); inspectorMode = mode;
            inspectorBody.Children[0].Visibility = mode == "properties" ? Visibility.Visible : Visibility.Collapsed;
            previewScroll.Visibility = mode == "preview" ? Visibility.Visible : Visibility.Collapsed; xmlSurface.Visibility = mode == "xml" ? Visibility.Visible : Visibility.Collapsed;
            propertyTab.Background = mode == "properties" ? B("#315F76") : soft; previewTab.Background = mode == "preview" ? B("#315F76") : soft; xmlTab.Background = mode == "xml" ? B("#315F76") : soft;
            if (mode == "preview") { preview.Start(Model.Document.Element(Model.Scope)); RefreshPreview(); } if (mode == "xml") RefreshXml();
        }
        private void SwitchMode(bool cardsMode) { CommitInspector(); scriptMode = cardsMode; graphSurface.Visibility = cardsMode ? Visibility.Collapsed : Visibility.Visible; scriptSurface.Visibility = cardsMode ? Visibility.Visible : Visibility.Collapsed; graphTab.Background = cardsMode ? soft : B("#315F76"); scriptTab.Background = cardsMode ? B("#315F76") : soft; RefreshGraph(); }
        private sealed class EventChoice { public string Caption { get; set; } public string Path { get; set; } public override string ToString() => Caption; }
        private void RefreshAll()
        {
            linkSource = null; if (ghost != null) ghost.Data = null;
            building = true;
            try
            {
                var choices = new List<EventChoice> { new() { Caption = "整份 XML 文件", Path = "" } };
                choices.AddRange(Model.Document.EventEntries().Take(10000).Select(e => new EventChoice { Caption = EventDocument.Attribute(e.Node, "identifier") + " · " + EditorText.Node(e.Node.Name.LocalName), Path = e.Path }));
                events.ItemsSource = choices; events.SelectedItem = choices.FirstOrDefault(e => e.Path == Model.Scope) ?? choices[0];
                documentLabel.Text = (projectPath != null ? Path.GetFileName(projectPath) : Model.Document.SourcePath != null ? Path.GetFileName(Model.Document.SourcePath) : "未命名草稿") + "  ·  " + (Model.ProjectDirty ? "有修改" : "已载入") + "  ·  原生 XML";
                undo.IsEnabled = Model.CanUndo; redo.IsEnabled = Model.CanRedo;
                RefreshPalette(); RefreshGraph(); RefreshInspector(); if (inspectorMode == "xml") RefreshXml();
            }
            finally { building = false; }
        }
        private void RefreshPalette()
        {
            if (palette == null || categories == null) return;
            palette.Children.Clear(); string category = categories.SelectedItem as string;
            var choices = catalog.All.Where(a => EditorText.Matches(a.Name + " " + a.Label, actionSearch.Text) && (category == "全部动作" || category == "分支与容器" && Catalog.IsContainer(a.Name) || a.Category == category)).ToArray();
            foreach (var action in choices)
            {
                var body = new StackPanel(); body.Children.Add(Text(action.Label, 13, ink, true)); body.Children.Add(Text(action.Name, 10, muted));
                var button = Btn("", () => AddAction(action.Name, Model.Selected)); button.Content = body; button.HorizontalContentAlignment = HorizontalAlignment.Left; button.Margin = new Thickness(0, 0, 0, 7); button.ToolTip = "拖入节点添加；拖入空白画布按当前上下文添加";
                button.PreviewMouseLeftButtonDown += (_, e) => paletteDown = e.GetPosition(button);
                button.PreviewMouseMove += (_, e) => { if (paletteDown is Point point && e.LeftButton == MouseButtonState.Pressed && (e.GetPosition(button) - point).Length > 5) { paletteDown = null; DragDrop.DoDragDrop(button, new DataObject("BaroEditor.Action", action.Name), DragDropEffects.Copy); } };
                button.PreviewMouseLeftButtonUp += (_, _) => paletteDown = null; palette.Children.Add(button);
            }
            if (choices.Length == 0) palette.Children.Add(Text("没有匹配的动作", 12, muted));
            palette.Children.Add(Btn("＋ 自定义 XML 节点", AddCustomNode));
        }
    }
}
