using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using BaroEditor;

internal static class CanvasDraftTests
{
    public static int Run(string scratch)
    {
        int count=0;
        void Check(bool value,string message) { if(!value) throw new Exception(message); count++; }
        void Throws(Action action,string message) { try { action(); } catch { count++; return; } throw new Exception(message); }
        var w=new Workspace(new EventDocument("<ScriptedEvent identifier='drafts'><WaitAction time='1'/></ScriptedEvent>"));
        string original=w.Document.Text;
        string a=w.AddFloating("CheckReputationAction",new NodePosition {X=500,Y=200},new Dictionary<string,string>{{"condition","gte 80"},{"identifier","coalition"}});
        Check(w.Document.Text==original && w.HasFloating,"Blank canvas drop leaves original XML unchanged");
        Check(w.Nodes("",out _).Single(n=>n.Path==a).Parent==null,"Floating card has no automatic parent edge");
        w.Change(d=>d.SetAttributes(w.SelectedLocalPath,new Dictionary<string,string>{{"condition","gt 90"}})); Check(w.Current.Attribute("condition").Value=="gt 90" && w.Document.Text==original,"Floating inspector changes only draft data");
        w.Undo(); Check(w.Current.Attribute("condition").Value=="gte 80","Floating attribute undo"); w.Redo();
        string b=w.AddFloating("WaitAction",new NodePosition{X=500,Y=400},new Dictionary<string,string>{{"time","2"}});
        w.Connect(a,b,"next"); Check(w.FloatingCount==1 && w.Nodes("",out _).Count(n=>n.Floating)==2 && w.Document.Text==original,"Floating actions can form a separate sequential chain");
        w.Connect("0",a,"next"); Check(!w.HasFloating && w.Document.Xml.Root.Elements().Count()==3,"Connecting a draft head adopts its entire sequential chain");
        Check(w.Document.Xml.Root.Elements().Last().Attribute("time").Value=="2","Tail stays attached to draft head");
        w.Undo(); Check(w.HasFloating && w.Document.Text==original && w.Current.Name.LocalName=="WaitAction","Undo attachment restores both documents and selection");
        w.Redo(); Check(!w.HasFloating && w.Document.Xml.Root.Elements().Count()==3,"Redo attachment restores both documents");
        w.Select("1"); w.DetachSelected(); Check(w.HasFloating && w.Document.Xml.Root.Elements().Count()==2,"Explicit detach moves selected subtree outside event");
        string project=Path.Combine(scratch,"draft-project.baroeditor"); w.SaveProject(project); var loaded=new Workspace(new EventDocument("<a/>")); loaded.ReadProject(project);
        Check(loaded.HasFloating && loaded.Current.Name.LocalName=="CheckReputationAction" && !loaded.ProjectDirty,"Project stores and restores draft XML, selection and layout");
        Check(loaded.CapturePositions()[loaded.Selected].X==500,"Floating layout survives project restore");
        Throws(loaded.RequireConnected,"XML output must account for unattached drafts");
        loaded.Change(d=>d.Delete(loaded.SelectedLocalPath)); Check(!loaded.HasFloating,"Deleting an unattached draft removes it from export diagnostics"); loaded.Undo(); Check(loaded.HasFloating,"Draft deletion is undoable");
        var f=new Workspace(new EventDocument("<ScriptedEvent><WaitAction time='1'/><WaitAction time='3'/></ScriptedEvent>")); string head=f.AddFloating("CheckMoneyAction",new NodePosition()); f.Connect(head,"1","Success");
        Check(f.Current.Name.LocalName=="WaitAction" && f.Current.Parent.Name.LocalName=="Success" && f.Document.Xml.Root.Elements().Count()==1,"An attached action can move into a floating branch");
        f.Undo(); Check(f.Document.Xml.Root.Elements().Count()==2 && f.FloatingCount==1,"Undo native-to-draft transfer");
        var invalid=new Workspace(new EventDocument("<ScriptedEvents><ScriptedEvent><WaitAction/></ScriptedEvent></ScriptedEvents>"));
        Throws(()=>invalid.Add("0","EventSet"),"EventSet cannot be added inside an event"); Throws(()=>invalid.Add("0","ScriptedEvent"),"ScriptedEvent cannot be added inside an event");
        string definition=invalid.AddFloating("ScriptedEvent",new NodePosition()); string stable=invalid.Document.Text;
        Throws(()=>invalid.Connect("0/0",definition,"next"),"Connecting a floating event definition inside another event is rejected"); Check(invalid.HasFloating && invalid.Document.Text==stable,"Rejected connection preserves floating work and original XML");
        var badImport=new Workspace(new EventDocument("<ScriptedEvent><EventSet/></ScriptedEvent>")); Check(EventStructure.Violations(badImport.Document.Xml.Root).Count()==1,"Invalid imported nesting can be reported without removing data"); Throws(badImport.RequireConnected,"Invalid nested definitions cannot be exported");
        var jumps=new Workspace(new EventDocument("<ScriptedEvents><ScriptedEvent><GoTo name='begin'/><Label name='begin'/></ScriptedEvent><ScriptedEvent><Label name='begin'/></ScriptedEvent></ScriptedEvents>"));
        Check(jumps.GoToTargets("0/0").Count==1 && jumps.PathOf(jumps.GoToTargets("0/0")[0])=="0/1","GoTo resolves label in its own event");
        jumps.Select("0/1"); jumps.Change(d=>d.SetAttributes(jumps.SelectedLocalPath,new Dictionary<string,string>{{"name","elsewhere"}})); Check(jumps.GoToTargets("0/0").Count==0,"Label index follows edits"); jumps.Undo(); Check(jumps.GoToTargets("0/0").Count==1,"Label index follows undo");
        jumps.Add("0","Label",attributes:new Dictionary<string,string>{{"name","begin"}}); Check(jumps.GoToTargets("0/0").Count==2,"Duplicate labels are exposed instead of silently choosing a target");
        foreach(var op in ComparisonCondition.Operators) { Check(ComparisonCondition.TrySplit(op+" 30",out string parsed,out string value)&&parsed==op&&value=="30","Split native comparison "+op); Check(ComparisonCondition.Compose(op,"30")==op+" 30","Write native comparison "+op); }
        Check(ComparisonCondition.TrySplit("gteq 40",out string alias,out string number)&&alias=="gte"&&number=="40","Native alias supported without touching raw XML");
        Check(ComparisonCondition.TrySplit("hello world",out string literal,out string full)&&literal=="eq"&&full=="hello world","Implicit equality preserves literal comparison value");
        return count;
    }
}
