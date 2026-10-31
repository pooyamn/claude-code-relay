using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Threading;

// Only SetClockGateBit writes target data: one documented bit at EC 0x1E09.
public sealed class CECClockGateProbe : IDisposable {
 [DllImport(@"C:\Program Files\PawnIO\PawnIOLib.dll")] static extern int pawnio_open(out IntPtr h);
 [DllImport(@"C:\Program Files\PawnIO\PawnIOLib.dll")] static extern int pawnio_load(IntPtr h,byte[] b,UIntPtr size);
 [DllImport(@"C:\Program Files\PawnIO\PawnIOLib.dll",CharSet=CharSet.Ansi)] static extern int pawnio_execute(IntPtr h,string name,ulong[] input,UIntPtr ni,[Out] ulong[] output,UIntPtr no,out UIntPtr returned);
 [DllImport(@"C:\Program Files\PawnIO\PawnIOLib.dll")] static extern int pawnio_close(IntPtr h);
 IntPtr handle;
 static readonly int[] Addresses={0x0250,0x0253,0x0258,0x0259,0x025f,0x0260,0x1638,0x16f7,0x1666,0x1e09,0x2e01,0x2e02,0x2e04,0x2e05,0x2e06,0x112d};
 static void Check(int hr){if(hr<0)Marshal.ThrowExceptionForHR(hr);}
 static bool Acquire(Mutex m){try{return m.WaitOne(3000);}catch(AbandonedMutexException){return true;}}
 public static Mutex CreateLease(string name){
  var acl=new MutexSecurity();
  foreach(var sid in new[]{WellKnownSidType.LocalSystemSid,WellKnownSidType.BuiltinAdministratorsSid})
   acl.AddAccessRule(new MutexAccessRule(new SecurityIdentifier(sid,null),MutexRights.FullControl,AccessControlType.Allow));
  bool created;return new Mutex(false,name,out created,acl);
 }
 public static bool AcquireLease(Mutex m){return Acquire(m);}
 T Bus<T>(Func<T> action){
  using(var isa=new Mutex(false,@"Global\Access_ISABUS.HTP.Method"))using(var ec=new Mutex(false,@"Global\Access_EC")){
   bool a=false,b=false;try{a=Acquire(isa);if(!a)throw new Exception("ISA lock timeout");b=Acquire(ec);if(!b)throw new Exception("EC lock timeout");return action();}
   finally{if(b)ec.ReleaseMutex();if(a)isa.ReleaseMutex();}
  }
 }
 ulong[] Execute(string n,ulong[] a,int count){var o=new ulong[count];UIntPtr returned;Check(pawnio_execute(handle,n,a,(UIntPtr)a.Length,o,(UIntPtr)count,out returned));if(returned.ToUInt64()!=(ulong)count)throw new Exception("Unexpected output count");return o;}
 void Out(int p,int v){Execute("ioctl_pio_outb",new ulong[]{(ulong)p,(ulong)v},0);}
 int In(int p){return checked((int)Execute("ioctl_pio_inb",new ulong[]{(ulong)p},1)[0]);}
 int Config(int i){Out(0x4e,i);return In(0x4f);}
 void Address(int address){
  if(Array.IndexOf(Addresses,address)<0)throw new Exception("Read address denied");
  Out(0x4e,0x2e);Out(0x4f,0x11);Out(0x4e,0x2f);Out(0x4f,address>>8);
  Out(0x4e,0x2e);Out(0x4f,0x10);Out(0x4e,0x2f);Out(0x4f,address&255);
  Out(0x4e,0x2e);Out(0x4f,0x12);Out(0x4e,0x2f);
 }
 int Read(int address){Address(address);return In(0x4f);}
 Dictionary<string,int> SnapshotRaw(){var r=new Dictionary<string,int>();foreach(int a in Addresses)r[a.ToString("X4")]=Read(a);return r;}
 public Dictionary<string,int> Snapshot(){return Bus(()=>SnapshotRaw());}
 public CECClockGateProbe(string module){
  try{Check(pawnio_open(out handle));var b=File.ReadAllBytes(module);Check(pawnio_load(handle,b,(UIntPtr)b.Length));
   Bus(()=>{Execute("ioctl_select_slot",new ulong[]{1},0);int id=0,version=0;
    try{Out(0x4e,0x87);Out(0x4e,0x01);Out(0x4e,0x55);Out(0x4e,0xaa);id=(Config(0x20)<<8)|Config(0x21);version=Config(0x22);}
    finally{Out(0x4e,2);Out(0x4f,2);}
    if(id!=0x5570||version!=2)throw new Exception("Chip/revision differs from validated read-only preflight");
    if(Read(0x0250)!=15)throw new Exception("RAM identity check failed");return 0;});
  }catch{Dispose();throw;}
 }
 public static void GuardIdle(Dictionary<string,int> r){
  GuardStable(r,0);
  if((r["2E06"]&0x29)!=0 || (r["2E01"]&7)!=0 || (r["0253"]&6)!=0 || r["0260"]!=0 || r["2E04"]!=0)
   throw new Exception("CEC is not quiescent; abort without a control write");
 }
 public static void GuardStable(Dictionary<string,int> r,int gate){
  if(r["1638"]!=0 || r["16F7"]!=0x20 || r["1E09"]!=gate || r["2E05"]!=0x3f || r["112D"]!=4 || (r["1666"]&1)!=1)
   throw new Exception("Unexpected control or CEC line state");
 }
 public static int MaskGate(int current,int savedBit){if(current<0||current>255||(savedBit!=0&&savedBit!=1))throw new ArgumentException();return (current&0xfe)|savedBit;}
 public Dictionary<string,int> SetClockGateBit(int bit){
  if(bit!=0&&bit!=1)throw new ArgumentException();
  return Bus(()=>{
   var before=SnapshotRaw();if(bit==1)GuardIdle(before);
   int current=before["1E09"],value=MaskGate(current,bit);
   if(value!=current){Address(0x1e09);Out(0x4f,value);} // Sole EC data write location.
   var after=SnapshotRaw();if(after["1E09"]!=value)throw new Exception("Clock-gate readback mismatch");return after;
  });
 }
 public void Dispose(){if(handle!=IntPtr.Zero){IntPtr h=handle;handle=IntPtr.Zero;Check(pawnio_close(h));}}
 public static string SelfTest(){
  for(int a=0;a<256;a++)for(int bit=0;bit<2;bit++){int v=MaskGate(a,bit);if((v&1)!=bit || (v&0xfe)!=(a&0xfe))throw new Exception("Mask test failed");}
  var r=new Dictionary<string,int>{{"1638",0},{"16F7",32},{"1E09",0},{"2E05",63},{"112D",4},{"1666",255},{"2E06",6},{"2E01",32},{"0253",1},{"0260",0},{"2E04",0}};
  GuardIdle(r);int rejected=0;
  foreach(string key in new[]{"1638","16F7","1E09","2E05","112D","1666","2E06","2E01","0253","0260","2E04"}){
   var bad=new Dictionary<string,int>(r);bad[key]=key=="1666"?254:key=="2E01"?33:key=="0253"?3:key=="2E06"?7:r[key]^1;
   try{GuardIdle(bad);}catch{rejected++;}
  }
  if(rejected!=11)throw new Exception("Unsafe state accepted");return "PASS: 512 masked-bit cases and 11 unsafe-precondition rejections; no hardware accessed";
 }
}
