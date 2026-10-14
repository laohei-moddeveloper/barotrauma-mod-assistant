using System;
using System.Collections.Generic;
using System.Linq;
using System.Windows;
using System.Windows.Controls;
using System.Xml.Linq;

namespace BaroEditor.Desktop
{
    public sealed partial class MainWindow
    {
        private sealed class OperatorChoice
        {
            public string Key { get; set; }
            public string Caption => ComparisonCondition.Label(Key);
            public override string ToString() => Caption;
        }
        private UIElement QuickComparison(string path,XElement node)
        {
            var row=new Grid(); row.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(89) }); row.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1,GridUnitType.Star) }); row.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(28) });
            ComparisonCondition.TrySplit(EventDocument.Attribute(node,"condition"),out string op,out string value);
            var operators=ComparisonCondition.Operators.Select(k=>new OperatorChoice { Key=k }).ToArray();
            var select=new ComboBox { ItemsSource=operators,SelectedItem=operators.First(o=>o.Key==op),FontSize=10,MinHeight=28,ToolTip="比较方式 · 大于 / 大于等于 / 等于 / 不等于 / 小于 / 小于等于" };
            var input=new TextBox { Text=value,Tag="比较值",FontSize=11,MinHeight=28,MaxLength=4096,Padding=new Thickness(5,4,5,4),Margin=new Thickness(4,0,4,0),ToolTip="比较值（数值、布尔或文本）；点击 ✓ 应用" };
            var apply=Btn("✓",()=>
            {
                string condition=ComparisonCondition.Compose(((OperatorChoice)select.SelectedItem).Key,input.Text);
                CommitInspector(); Model.Select(path); string key=node.Attributes().FirstOrDefault(a=>a.Name.LocalName.Equals("condition",StringComparison.OrdinalIgnoreCase))?.Name.ToString()??"condition";
                Model.Change(doc=>doc.SetAttributes(Model.SelectedLocalPath,new Dictionary<string,string> { [key]=condition })); RefreshAll(); SetStatus("比较条件已更新："+condition+" · 可撤销");
            }); apply.Margin=new Thickness(0); apply.Padding=new Thickness(0); apply.ToolTip="应用比较方式与值";
            At(row,select); At(row,input,0,1); At(row,apply,0,2); return row;
        }
        private void LocateGoTo(string path)
        {
            CommitInspector(); var targets=Model.GoToTargets(path); string name=EventDocument.Attribute(Model.Element(path),"name");
            if(targets.Count==0) throw new InvalidOperationException("同一事件中找不到标签："+name+"。请检查 GoTo 的 name 与 Label 的 name。");
            if(targets.Count==1) { FocusNode(Model.PathOf(targets[0])); return; }
            var menu=new ContextMenu { Background=panel,Foreground=ink };
            foreach(var target in targets)
            {
                string targetPath=Model.PathOf(target); var item=new MenuItem { Header="标签 "+name+" · "+targetPath };
                item.Click+=(_,_)=>Safe(()=>FocusNode(targetPath)); menu.Items.Add(item);
            }
            menu.PlacementTarget=this; menu.IsOpen=true; SetStatus("标签重名：请选择需要定位的目标。",true);
        }
        private bool ConfirmConnectedOutput()
        {
            if (EventStructure.Violations(Model.Document.Xml.Root).Any()) throw new InvalidOperationException("事件组（EventSet）和脚本事件（ScriptedEvent/TraitorEvent）不能嵌套在事件内部。请修正后再输出 XML；保存工程会保留原文。");
            return !Model.HasFloating || Confirm("还有 "+Model.FloatingCount+" 组草稿未接入事件。\n\n本次 XML 输出只包含已连接的事件内容，悬空草稿仍留在工作台。保存 .baroeditor 工程才能保留全部草稿。\n\n仍然只输出已连接内容？");
        }
        private void HighlightRelated(string path, string other = null)
        {
            var related=new HashSet<string>(); if(path!=null) related.Add(path); if(other!=null) related.Add(other);
            var selected=nodes.FirstOrDefault(n=>n.Path==path);
            if(selected?.Name=="GoTo") foreach(var target in Model.GoToTargets(path)) related.Add(Model.PathOf(target));
            if(selected?.Name=="Label") foreach(var source in nodes.Where(n=>n.Name=="GoTo")) if(Model.GoToTargets(source.Path).Contains(selected.Xml)) related.Add(source.Path);
            foreach(var pair in cards)
            {
                bool active=pair.Key==Model.Selected,linked=related.Contains(pair.Key);
                pair.Value.BorderBrush=active?accent:linked?amber:line; pair.Value.BorderThickness=new Thickness(active||linked?2:1); pair.Value.Background=linked?soft:panel;
            }
            foreach(var edge in edges) edge.Curve.StrokeThickness=related.Contains(edge.From.Path)&&related.Contains(edge.To.Path)?3:edge.Sequence?1.6:1.7;
        }
    }
}
