using System;
using System.IO;
using System.Linq;
using System.Xml.Linq;
using BaroEditor;

internal static class LocalizationTests
{
    public static int Run(string scratch)
    {
        int checks=0;
        void Check(bool value,string message) { if(!value) throw new Exception(message); checks++; }
        void Throws(Action action,string message) { try { action(); } catch { checks++; return; } throw new Exception(message); }
        string Save(string name,string text) { string p=Path.Combine(scratch,name); File.WriteAllText(p,text); return p; }
        var zh=Save("zh.xml","<infotexts language='Simplified Chinese'><event.hello>你好，[name]！\n第二行</event.hello><entity.captain>船长</entity.captain><event.hello>随机备选</event.hello></infotexts>");
        var en=Save("en.xml","<infotexts language='English'><event.hello>Hello, [name]!</event.hello><entity.captain>Captain</entity.captain></infotexts>");
        var loc=new Localization(); loc.Import(new[]{en,zh});
        Check(loc.Language=="Simplified Chinese" && loc.Count==2,"Prefer imported Simplified Chinese and deterministic duplicate alternatives");
        Check(loc.Resolve("EVENT.HELLO")=="你好，[name]！\n第二行","Case insensitive tag resolution preserves multiline text");
        Check(loc.Resolve("literal text")=="literal text","Unknown/literal text retained");
        var structured=XElement.Parse("<ConversationAction><Text tag='event.hello'><Replace tag='[name]' value='entity.captain'/><Replace tag='[runtime]' targettag='player'/></Text></ConversationAction>");
        string original=structured.ToString(); Check(loc.Text(structured)=="你好，船长！\n第二行" && structured.ToString()==original,"Structured static Text replacement without XML edits");
        loc.Select("English"); Check(loc.Text(structured)=="Hello, Captain!","Switch languages");
        var overrideFile=Save("override.xml","<infotexts language='English'><event.hello>Overridden</event.hello></infotexts>"); loc.Import(new[]{overrideFile}); Check(loc.Resolve("event.hello")=="Overridden","Later explicitly imported file overrides existing keys");
        var bad=Save("bad.xml","<!DOCTYPE x [<!ENTITY leak SYSTEM 'file:///C:/Windows/win.ini'>]><infotexts language='English'><x>&leak;</x></infotexts>");
        long version=loc.Revision; Throws(()=>loc.Import(new[]{zh,bad}),"DTD must be rejected"); Check(loc.Revision==version && loc.Resolve("event.hello")=="Overridden","Failed import leaves previous complete catalog unchanged");
        var wrong=Save("event.xml","<ScriptedEvent identifier='no'/>"); Throws(()=>loc.Import(new[]{wrong}),"Event XML is not localization");
        var huge=new LocalizationData(); huge.Languages["English"]=new(){["x"]=new string('x',65537)}; Throws(()=>loc.Restore(huge),"Oversized translation rejected"); Check(loc.Resolve("event.hello")=="Overridden","Failed restore transactional");
        var work=new Workspace(new EventDocument("<ScriptedEvent><ConversationAction text='event.hello'/></ScriptedEvent>"));
        work.Localization.Import(new[]{zh,en}); string xml=work.Document.Text;
        Check(work.Nodes("你好",out _).Any(n=>n.Name=="ConversationAction"),"Search localized content");
        work.Localization.Select("English"); Check(work.Nodes("Hello",out _).Any(n=>n.Name=="ConversationAction") && !work.Nodes("你好",out _).Any(),"Search index follows locale revision");
        string project=Path.Combine(scratch,"localization.baroeditor"); work.SaveProject(project); Check(!work.ProjectDirty,"Saving embedded translations marks project clean");
        var loaded=new Workspace(new EventDocument("<a/>")); loaded.ReadProject(project);
        Check(loaded.Localization.Language=="English" && loaded.Localization.Text(loaded.Document.Element("0"))=="Hello, [name]!","Project restores embedded catalog without source file reads");
        Check(loaded.Document.Text==xml && !loaded.ProjectDirty,"Localization never rewrites native event tags");
        loaded.Localization.Clear(); Check(loaded.ProjectDirty && loaded.Localization.Resolve("event.hello")=="event.hello","Clearing locale invalidates project state");
        var realPath="D:/steam/steamapps/common/Barotrauma/Content/Texts/SimplifiedChinese/SimplifiedChineseVanilla.xml";
        if(File.Exists(realPath)) { var watch=System.Diagnostics.Stopwatch.StartNew(); var real=new Localization(); real.Import(new[]{realPath}); Check(real.Count>5000 && real.Resolve("loading")=="加载中…","Real native localization file imports"); Console.WriteLine("Native localization: "+real.Count+" entries, "+watch.ElapsedMilliseconds+" ms"); }
        return checks;
    }
}
