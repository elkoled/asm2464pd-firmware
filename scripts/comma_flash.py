#!/usr/bin/env python3
# reliable comma flash: pure control transfers + converge verify/rewrite (writes are ~1.3% flaky, reads solid).
# input = FULL flash image (config@0x0 + wrapped fw@0x100), written at offset 0.
import ctypes, fcntl, os, sys, time, glob
def find():
  for d in glob.glob('/sys/bus/usb/devices/*'):
    try:
      if open(d+'/idVendor').read().strip()=='add1' and open(d+'/idProduct').read().strip()=='0001': return d
    except OSError: pass
  return None
d=find(); bus=int(open(d+'/busnum').read()); dev=int(open(d+'/devnum').read())
FD=os.open(f'/dev/bus/usb/{bus:03d}/{dev:03d}', os.O_RDWR)
C=lambda bt,br,wv,wi,wl,to,dp: (lambda s:s)(type('C',(ctypes.Structure,),{'_fields_':[('a',ctypes.c_uint8),('b',ctypes.c_uint8),('c',ctypes.c_uint16),('e',ctypes.c_uint16),('f',ctypes.c_uint16),('g',ctypes.c_uint32),('h',ctypes.c_void_p)]})(bt,br,wv,wi,wl,to,dp))
def wr(a,v): fcntl.ioctl(FD,0xC0185500,C(0x40,0xE5,a&0xFFFF,v&0xFFFF,0,2000,None))
def rd(a,n=1):
  buf=(ctypes.c_ubyte*n)(); fcntl.ioctl(FD,0xC0185500,C(0xC0,0xE4,a&0xFFFF,0,n,2000,ctypes.cast(buf,ctypes.c_void_p))); return bytes(buf)
def wrb(base,data):
  for i,b in enumerate(data): wr(base+i,b)
def ftx(cmd,addr=0,dl=0,al=0x07,mode=0x00):
  wr(0xC8AD,mode);wr(0xC8AE,0);wr(0xC8AF,0);wr(0xC8AA,cmd);wr(0xC8AC,al)
  wr(0xC8A1,addr&0xFF);wr(0xC8A2,(addr>>8)&0xFF);wr(0xC8AB,(addr>>16)&0xFF)
  wr(0xC8A3,(dl>>8)&0xFF);wr(0xC8A4,dl&0xFF);wr(0xC8A9,0x01)
  for _ in range(100000):
    if not (rd(0xC8A9,1)[0]&0x01): break
  for _ in range(4): wr(0xC8AD,0)
def wren():
  wr(0xC8AD,0);wr(0xC8AA,0x06);wr(0xC8AC,0x04);wr(0xC8A3,0);wr(0xC8A4,0);wr(0xC8A9,0x01)
  for _ in range(100000):
    if not (rd(0xC8A9,1)[0]&0x01): break
def rdsr(): ftx(0x05,dl=1,al=0x04); return rd(0x7000,1)[0]
def wait_wip(t=10.0):
  t0=time.monotonic()
  while time.monotonic()-t0<t:
    if not (rdsr()&0x01): return
    time.sleep(0.005)
def finit():
  wr(0xCC33,0x04);v=rd(0xCA81,1)[0];wr(0xCA81,v|0x01);wr(0xC805,0x02);wr(0xC8A6,0x04)
  for _ in range(5):
    wren();wrb(0x7000,bytes(4));ftx(0x01,dl=1,al=0x04,mode=0x01);time.sleep(0.01)
    if not (rdsr()&0x1C): break
def fread(a,n):
  out=bytearray();o=0
  while o<n:
    w=min(4096,n-o);ftx(0x03,addr=a+o,dl=max(4096,w),al=0x07);r=0
    while r<w:
      k=min(255,w-r);out.extend(rd(0x7000+r,k));r+=k
    o+=w
  return bytes(out)
def berase(a): wren();ftx(0xD8,addr=a,dl=0,al=0x07);wait_wip()
def pprog(a,n): wren();ftx(0x02,addr=a,dl=n,al=0x07,mode=0x01);wait_wip()
def wchunk(a,ch):
  p=ch+bytes((-len(ch))%4); wrb(0x7000,p); pprog(a,len(ch))

fw=open(sys.argv[1],'rb').read()
print(f"flash {len(fw)} bytes @0 via control transfers",flush=True)
finit()
for blk in range(0,(len(fw)+0xFFFF)&~0xFFFF,0x10000):
  print(f"  erase 0x{blk:05X}",flush=True); berase(blk)
# write pass
for w in range(0,len(fw),128): wchunk(w,fw[w:w+128])
# converge: verify + rewrite mismatched chunks
for p in range(12):
  got=fread(0,len(fw))
  bad=[w for w in range(0,len(fw),128) if got[w:w+128]!=fw[w:w+128]]
  print(f"  pass {p}: {len(bad)} bad chunks",flush=True)
  if not bad: print("VERIFY OK"); break
  for w in bad: wchunk(w,fw[w:w+128])
else:
  print("VERIFY FAILED (did not converge)")
