const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync(require('node:path').join(__dirname,'progress-sync.js'),'utf8').replace(/^import[\s\S]*?;\n/gm,'');

const cloud=new Map();
const listeners=new Set();
let lock=Promise.resolve();
let dropNextResult=false;
function notify(){
  for(const {path,fn} of listeners) fn({
    docChanges:()=>[...cloud].filter(([key])=>key.startsWith(path+'/')).map(([,value])=>({
      type:'modified',doc:{data:()=>value}
    })),
    metadata:{fromCache:false},
  });
}
function device(legacy={}) {
  const storage=new Map();
  const caches=new Map([[null,legacy]]);
  const nodes=new Map();
  let authenticate;
  let current;
  const navigator={onLine:true};
  const localStorage={
    get length(){return storage.size;},key:i=>[...storage.keys()][i],
    getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),
    removeItem:k=>storage.delete(k)
  };
  const events=new Map();
  function boot(){
    const context=vm.createContext({
      firebaseConfig:{}, initializeApp:()=>{},getAuth:()=>({}), getFirestore:()=>{},
      collection:(_, ...parts)=>parts.join('/'), doc:(base,...parts)=>[base,...parts].filter(Boolean).join('/'),
      onSnapshot(path,opts,fn){
        const listener={path,fn};listeners.add(listener);queueMicrotask(notify);
        return ()=>listeners.delete(listener);
      },
      onAuthStateChanged:(_,fn)=>{authenticate=fn;},
      runTransaction(_,run){
        const attempt=lock.then(async()=>{
          const writes=[];
          const result=await run({
            get:async path=>({data:()=>cloud.get(path),exists:()=>cloud.has(path)}),
            set:(path,value)=>writes.push([path,value])
          });
          for(const [path,value] of writes)cloud.set(path,value);
          notify();
          if(dropNextResult){dropNextResult=false;throw Error('response lost');}
          return result;
        });
        lock=attempt.catch(()=>{});
        return attempt;
      },
      GoogleAuthProvider:class {setCustomParameters(){}},
      document:{getElementById:id=>{
        if(!nodes.has(id))nodes.set(id,{addEventListener(){},hidden:true});
        return nodes.get(id);
      }},
      window:{cet6Progress:{
        words:['abandon','record','use'],
        read:uid=>caches.get(uid)||{},
        show:(uid,patch)=>{
          current=uid;
          if(patch)caches.set(uid,{...caches.get(uid),...patch});
        }
      },addEventListener:(name,fn)=>events.set(name,fn)},
      navigator,localStorage,crypto:require('node:crypto').webcrypto,setInterval(){},
      console:{warn(){}},Date,Map,Object,Number,JSON,Array,Math,String
    });
    vm.runInContext(source,context);
    return context;
  }
  let context=boot();
  return {
    login:uid=>authenticate(uid?{uid}:null), navigator, storage, show:()=>caches.get(current)??{},
    click(index,field,value){context.window.cet6Progress.record(index,field,value);},
    resume(){navigator.onLine=true;events.get('online')();},
    reload(uid){authenticate(null);context=boot();authenticate({uid});},
  };
}
const wait=()=>new Promise(resolve=>setTimeout(resolve,25));
(async()=>{
  const phone=device({0:{n:2,em:true,zm:false}}), tablet=device({0:{n:4,em:false,zm:true},1:{n:1,em:true,zm:false}}), laptop=device();
  phone.login('test-user');await wait();
  assert.equal(phone.show()[0].n,2);
  tablet.login('test-user');laptop.login('test-user');await wait();
  assert.equal(laptop.show()[0].n,2);
  assert.equal(laptop.show()[1].em,true);
  assert.equal(laptop.show()[0].zm,true);
  phone.click(0,'zm',true);
  laptop.click(0,'em',false);
  phone.click(0,'n',1);
  laptop.click(0,'n',1);
  await wait();
  assert.equal(tablet.show()[0].n,4);
  assert.equal(tablet.show()[0].zm,true);
  assert.equal(tablet.show()[0].em,false);
  tablet.navigator.onLine=false;
  tablet.click(0,'n',-1);
  tablet.reload('test-user');
  await wait();
  assert.equal(phone.show()[0].n,4);
  tablet.resume();await wait();
  assert.equal(phone.show()[0].n,3);
  dropNextResult=true;
  phone.click(0,'n',1);
  await wait();
  assert.equal(laptop.show()[0].n,4);
  phone.reload('test-user');await wait();
  assert.equal(laptop.show()[0].n,4);
  assert.equal([...phone.storage.keys()].filter(key=>key.includes(':op:')).length,0);
  laptop.login('other-user');await wait();
  assert.equal(laptop.show()[0],undefined);
  phone.login(null);
  assert.equal(phone.show()[0].n,2);
  console.log('Passed: three-device updates, concurrent increments, offline reload, retry de-duplication, migration, account isolation.');
})().catch(err=>{console.error(err);process.exitCode=1;});
