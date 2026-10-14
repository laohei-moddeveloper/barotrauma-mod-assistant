using System;
using System.Linq;
using System.Xml.Linq;

namespace BaroEditor
{
    public static class ComparisonCondition
    {
        public static readonly string[] Operators = { "gt", "gte", "eq", "neq", "lt", "lte" };
        public static string Label(string op) => op switch { "gt"=>"> gt", "gte"=>"≥ gte", "eq"=>"= eq", "neq"=>"≠ neq", "lt"=>"< lt", "lte"=>"≤ lte", _=>op };
        public static bool Applies(XElement node) => node.Name.LocalName is "CheckDataAction" or "CheckReputationAction";
        public static bool TrySplit(string raw,out string op,out string value)
        {
            raw=raw??""; int separator=raw.IndexOf(' ');
            string token=separator<0?"":raw[..separator].ToLowerInvariant();
            op=token switch { "e" or "eq" or "equals"=>"eq", "ne" or "neq" or "notequals" or "!" or "!e" or "!eq" or "!equals"=>"neq", "gt" or "greaterthan"=>"gt", "gte" or "gteq" or "greaterthanequals"=>"gte", "lt" or "lessthan"=>"lt", "lte" or "lteq" or "lessthanequals"=>"lte", _=>"eq" };
            value=separator>=0 && token is "e" or "eq" or "equals" or "ne" or "neq" or "notequals" or "!" or "!e" or "!eq" or "!equals" or "gt" or "greaterthan" or "gte" or "gteq" or "greaterthanequals" or "lt" or "lessthan" or "lte" or "lteq" or "lessthanequals" ? raw[(separator+1)..] : raw;
            return value.Length>0;
        }
        public static string Compose(string op,string value)
        {
            if(!Operators.Contains(op)) throw new ArgumentException("请选择比较方式。");
            if(string.IsNullOrWhiteSpace(value) || value.Length>4096) throw new ArgumentException("请输入比较值（最多 4096 字符）。");
            return op+" "+value;
        }
    }
}
