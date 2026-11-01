using System;
using System.IO;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

public static class ResonancePckEngine {
    public static Action<string,int> Status;
    public static int HashProgress = 5;
    const int Chunk = 4 * 1024 * 1024;
    const long HeaderLimit = 128L * 1024 * 1024;
    sealed class Entry {
        public uint Id, Block, Lang;
        public long Size, Offset;
        public int SizePos, StartPos, EntrySize;
        public long NewOffset, NewSize;
        public string Replacement;
    }
    sealed class Info { public bool Little; public byte[] Header; public List<Entry> Entries = new List<Entry>(); }
    static long Number(object x) { return Convert.ToInt64(x); }
    static Dictionary<string,object> Object(object x) { return (Dictionary<string,object>)x; }
    static object[] Array(object x) { return (object[])x; }
    static Dictionary<string,object> ReadSpec(string file) {
        var json = new JavaScriptSerializer(); json.MaxJsonLength = 32 * 1024 * 1024;
        return Object(json.DeserializeObject(File.ReadAllText(file, System.Text.Encoding.UTF8)));
    }
    public static string PathUnder(string root, string relative) {
        if (String.IsNullOrWhiteSpace(relative) || Path.IsPathRooted(relative) || relative.IndexOf(':') >= 0)
            throw new InvalidDataException("UNSAFE_RELATIVE_PATH");
        foreach (string part in relative.Replace('\\','/').Split('/'))
            if (part == "" || part == "." || part == "..") throw new InvalidDataException("UNSAFE_RELATIVE_PATH");
        string prefix = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar,Path.AltDirectorySeparatorChar) + Path.DirectorySeparatorChar;
        string full = Path.GetFullPath(Path.Combine(root,relative.Replace('/',Path.DirectorySeparatorChar)));
        if (!full.StartsWith(prefix,StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("UNSAFE_RELATIVE_PATH");
        // Reject descendant links before reading/writing through a redirected path.
        string parent = full;
        while (parent != null && parent.Length >= prefix.Length) {
            if ((File.Exists(parent) || Directory.Exists(parent)) && (File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0)
                throw new InvalidDataException("REDIRECTED_GAME_PATH");
            parent = Path.GetDirectoryName(parent);
        }
        return full;
    }
    public static string Hash(string file) {
        using (var stream = File.OpenRead(file)) using (var sha = SHA256.Create()) {
            byte[] buffer=new byte[Chunk];int n,blocks=0;
            while((n=stream.Read(buffer,0,buffer.Length))>0) {
                sha.TransformBlock(buffer,0,n,buffer,0);blocks++;
                if(Status!=null && blocks%64==0)Status("SHA-256 "+(stream.Position/(1024*1024))+" MB",HashProgress);
            }
            sha.TransformFinalBlock(new byte[0],0,0);
            return BitConverter.ToString(sha.Hash).Replace("-","").ToLowerInvariant();
        }
    }
    public static void CopyOriginal(string source,string destination) {
        using(var input=File.OpenRead(source))using(var output=new FileStream(destination,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
            byte[] buffer=new byte[Chunk];int n,blocks=0;
            while((n=input.Read(buffer,0,buffer.Length))>0) {output.Write(buffer,0,n);blocks++;if(Status!=null && blocks%64==0)Status("Backup "+(input.Position/(1024*1024))+" MB",94);}
            output.Flush(true);
        }
    }
    static uint U32(byte[] data, int p, bool little) {
        if (p < 0 || p+4 > data.Length) throw new InvalidDataException("AKPK_HEADER_BOUNDS");
        if (little) return (uint)data[p] | ((uint)data[p+1]<<8) | ((uint)data[p+2]<<16) | ((uint)data[p+3]<<24);
        return ((uint)data[p]<<24) | ((uint)data[p+1]<<16) | ((uint)data[p+2]<<8) | data[p+3];
    }
    static ulong U64(byte[] d,int p,bool little) {
        return little ? U32(d,p,little) | ((ulong)U32(d,p+4,little)<<32) : ((ulong)U32(d,p,little)<<32) | U32(d,p+4,little);
    }
    static void Put(byte[] d,int p,ulong value,int width,bool little) {
        if (p<0 || p+width>d.Length) throw new InvalidDataException("AKPK_HEADER_BOUNDS");
        for(int i=0;i<width;i++) d[p+(little?i:width-1-i)] = (byte)(value>>(8*i));
    }
    static byte[] Read(FileStream f,long offset,int count) {
        f.Position=offset;byte[] data=new byte[count];int p=0;
        while(p<count) {int n=f.Read(data,p,count-p);if(n<=0)throw new EndOfStreamException("AKPK_TRUNCATED");p+=n;}
        return data;
    }
    static List<Entry> Table(FileStream f,int pos,int size,bool little) {
        var result=new List<Entry>();if(size<4)return result;
        byte[] data=Read(f,pos,size);uint count=U32(data,0,little);if(count==0)return result;
        if((size-4)%count!=0)throw new InvalidDataException("AKPK_TABLE_INVALID");
        int es=checked((int)((size-4)/count));if(es!=20 && es!=24)throw new InvalidDataException("AKPK_ENTRY_UNSUPPORTED");
        for(int i=0;i<count;i++) {
            int p=checked(4+i*es);var e=new Entry();e.Id=U32(data,p,little);e.Block=U32(data,p+4,little);
            ulong sz=es==20?U32(data,p+8,little):U64(data,p+8,little);if(sz>Int64.MaxValue)throw new InvalidDataException("AKPK_SIZE_OVERFLOW");
            e.Size=(long)sz;uint start=U32(data,p+(es==20?12:16),little);e.Lang=U32(data,p+(es==20?16:20),little);
            e.Offset=checked((long)start*(e.Block==0?1:e.Block));e.EntrySize=es;
            e.SizePos=pos+p+8;e.StartPos=pos+p+(es==20?12:16);result.Add(e);
        }
        return result;
    }
    static Info Parse(FileStream f) {
        if(f.Length<28)throw new InvalidDataException("AKPK_TRUNCATED");
        byte[] prefix=Read(f,0,(int)Math.Min(64,f.Length));
        if(prefix[0]!=65||prefix[1]!=75||prefix[2]!=80||prefix[3]!=75)throw new InvalidDataException("AKPK_MAGIC_INVALID");
        bool little=true;bool found=false;
        foreach(bool order in new bool[]{true,false}) {
            uint h=U32(prefix,4,order),flag=U32(prefix,8,order);
            if(h>=8 && h<=HeaderLimit && flag<65536 && U32(prefix,12,order)<=HeaderLimit && U32(prefix,16,order)<=HeaderLimit && U32(prefix,20,order)<=HeaderLimit) {little=order;found=true;break;}
        }
        if(!found)throw new InvalidDataException("AKPK_ENDIAN_INVALID");
        uint hs=U32(prefix,4,little);long s1=U32(prefix,12,little),s2=U32(prefix,16,little),s3=U32(prefix,20,little);
        bool fourth=s1+s2+s3+16<hs;long s4=fourth?U32(prefix,24,little):0;long pos=fourth?28:24;
        if(s4>HeaderLimit || pos+s1+s2+s3+s4>Math.Min(HeaderLimit,f.Length))throw new InvalidDataException("AKPK_SECTION_INVALID");
        if(Table(f,(int)(pos+s1),(int)s2,little).Count>0 || Table(f,(int)(pos+s1+s2+s3),(int)s4,little).Count>0)
            throw new InvalidDataException("AKPK_BANK_EXTERNAL_UNSUPPORTED");
        var info=new Info();info.Little=little;info.Entries=Table(f,(int)(pos+s1+s2),(int)s3,little);
        if(info.Entries.Count==0)throw new InvalidDataException("AKPK_NO_MEDIA");
        info.Entries.Sort((a,b)=>a.Offset.CompareTo(b.Offset));long header=info.Entries[0].Offset;
        if(header<pos+s1+s2+s3+s4 || header>HeaderLimit)throw new InvalidDataException("AKPK_PAYLOAD_INVALID");
        long end=header;var keys=new HashSet<string>();
        foreach(var e in info.Entries) {
            if(e.Offset<end||e.Size<1||e.Offset>f.Length-e.Size||!keys.Add(e.Lang+":"+e.Id))throw new InvalidDataException("AKPK_MEDIA_INVALID");
            end=e.Offset+e.Size;
        }
        info.Header=Read(f,0,(int)header);return info;
    }
    static void Copy(FileStream source,FileStream target,long offset,long count,byte[] buffer) {
        source.Position=offset;
        while(count>0) {int n=source.Read(buffer,0,(int)Math.Min(buffer.Length,count));if(n<=0)throw new EndOfStreamException("PAYLOAD_TRUNCATED");target.Write(buffer,0,n);count-=n;}
    }
    public static long Build(string original,string output,string manifestFile,string packageRoot,Action<string,int> progress) {
        var manifest=ReadSpec(manifestFile);var spec=Object(manifest["pck"]);
        if(new FileInfo(original).Length!=Number(spec["base_size"]) || Hash(original)!=(string)spec["base_sha256"])
            throw new InvalidDataException("ORIGINAL_PCK_VERSION_MISMATCH");
        if(File.Exists(output))throw new IOException("PCK_TEMP_ALREADY_EXISTS");
        var replacements=new Dictionary<string,Dictionary<string,object>>();
        foreach(object item in Array(spec["replacements"])) {
            var r=Object(item);if(Number(r["language_id"])!=1)throw new InvalidDataException("NON_ENGLISH_TARGET");
            string k=Number(r["language_id"])+":"+Number(r["source_id"]);if(replacements.ContainsKey(k))throw new InvalidDataException("DUPLICATE_REPLACEMENT");
            string path=PathUnder(packageRoot,(string)r["payload"]);
            if(new FileInfo(path).Length!=Number(r["size"]) || Hash(path)!=(string)r["sha256"])throw new InvalidDataException("UA_PAYLOAD_HASH_MISMATCH");
            using(var check=File.OpenRead(path)) {byte[] riff=Read(check,0,12);if(System.Text.Encoding.ASCII.GetString(riff,0,4)!="RIFF"||System.Text.Encoding.ASCII.GetString(riff,8,4)!="WAVE")throw new InvalidDataException("UA_WEM_INVALID");}
            replacements.Add(k,r);
        }
        using(var source=File.OpenRead(original)) {
            Info info=Parse(source);long pos=info.Header.Length;int matched=0;
            foreach(var e in info.Entries) {
                long block=e.Block==0?1:e.Block;pos=checked(((pos+block-1)/block)*block);e.NewOffset=pos;
                Dictionary<string,object> r;
                if(replacements.TryGetValue(e.Lang+":"+e.Id,out r)) {e.Replacement=PathUnder(packageRoot,(string)r["payload"]);e.NewSize=Number(r["size"]);matched++;}else e.NewSize=e.Size;
                if(pos/block>UInt32.MaxValue || (e.EntrySize==20 && e.NewSize>UInt32.MaxValue))throw new InvalidDataException("AKPK_ENTRY_OVERFLOW");
                Put(info.Header,e.SizePos,(ulong)e.NewSize,e.EntrySize==20?4:8,info.Little);Put(info.Header,e.StartPos,(ulong)(pos/block),4,info.Little);pos=checked(pos+e.NewSize);
            }
            if(matched!=replacements.Count || pos!=Number(spec["output_size"]))throw new InvalidDataException("PCK_LAYOUT_MISMATCH");
            byte[] buffer=new byte[Chunk],zero=new byte[Chunk];
            using(var target=new FileStream(output,FileMode.CreateNew,FileAccess.Write,FileShare.None)) {
                target.Write(info.Header,0,info.Header.Length);int index=0;
                foreach(var e in info.Entries) {
                    long padding=e.NewOffset-target.Position;while(padding>0){int n=(int)Math.Min(zero.Length,padding);target.Write(zero,0,n);padding-=n;}
                    if(e.Replacement!=null)using(var ua=File.OpenRead(e.Replacement))Copy(ua,target,0,e.NewSize,buffer);
                    else Copy(source,target,e.Offset,e.Size,buffer);
                    index++;if(progress!=null && (index%1000==0 || index==info.Entries.Count))progress("PCK "+index+" / "+info.Entries.Count,20+(int)(65.0*index/info.Entries.Count));
                }
                target.Flush(true);
            }
        }
        HashProgress=90;if(progress!=null)progress("SHA-256 PCK",90);
        if(new FileInfo(output).Length!=Number(spec["output_size"]) || Hash(output)!=(string)spec["output_sha256"])
            throw new InvalidDataException("OUTPUT_PCK_VERIFICATION_FAILED");
        return Number(spec["output_size"]);
    }
    public static void ExtractExternal(string destination,string dataFolder) {
        var assembly=System.Reflection.Assembly.GetExecutingAssembly();
        foreach(string name in new string[]{"manifest.json","INSTALL.ps1","INSTALLER.ico","INSTALLER.png"}) {
            using(var input=assembly.GetManifestResourceStream("Resonance."+name)) {
                if(input==null)throw new InvalidDataException("INSTALLER_RESOURCE_MISSING");
                using(var output=File.Create(Path.Combine(destination,name)))input.CopyTo(output);
            }
        }
        string root=Path.Combine(Path.GetDirectoryName(assembly.Location),dataFolder);
        if(!Directory.Exists(root))throw new DirectoryNotFoundException("INSTALLER_DATA_FOLDER_MISSING: "+dataFolder);
        Environment.SetEnvironmentVariable("COLDVOICE_UA_ROOT",root);
    }
}
