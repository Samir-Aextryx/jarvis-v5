const fs=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
const callbacks={};
const made=[];
class FakeWindow {
  constructor(options){this.options=options;this.events={};this.webContents={session:{setPermissionRequestHandler(){},setPermissionCheckHandler(){}},setWindowOpenHandler(){},on(){}};made.push(this);}
  on(name,fn){this.events[name]=fn;}
  isDestroyed(){return false;}
  async loadURL(url){this.url=url;}
  show(){} focus(){}
}
const main={webContents:{send(){}},isDestroyed:()=>false};
const electron={app:{setName(){},setAppUserModelId(){},commandLine:{appendSwitch(){}},getPath:()=>'/app/Jarvis.exe',requestSingleInstanceLock:()=>false,quit(){}},nativeTheme:{},BrowserWindow:FakeWindow,ipcMain:{handle:(name,fn)=>callbacks[name]=fn}};
const context=vm.createContext({require:name=>name==='electron'?electron:require(name),URL,Date,process,main,__dirname:'/app'});
vm.runInContext(fs.readFileSync('desktop/main.cjs','utf8'),context);
vm.runInContext('window=main',context);
(async()=>{
  const open=callbacks['jarvis-open-map'];
  const event={sender:main.webContents,senderFrame:{url:'http://127.0.0.1:8345/'}};
  await assert.rejects(open({...event,sender:{}},'http://127.0.0.1:4173/'));
  for(const url of ['https://example.com/','file:///C:/test','http://user:secret@127.0.0.1:4173/'])await assert.rejects(open(event,url));
  await open(event,'http://127.0.0.1:4173/#lat=39&lon=-98');
  await open(event,'http://127.0.0.1:4173/#lat=46.8&lon=8.23');
  assert.equal(made.length,1);
  assert.equal(new URL(made[0].url).hash,'#lat=46.8&lon=8.23');
  assert.equal(made[0].options.webPreferences.nodeIntegration,false);
  assert.equal(made[0].options.webPreferences.sandbox,true);
  console.log('Native map sender, URL and window-reuse checks passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
