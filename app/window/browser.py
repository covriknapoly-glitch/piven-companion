from __future__ import annotations

import json
import os
import threading
import time

import clr
from System import Func, Type, Uri
import System.Windows.Forms as WinForms
from webview.util import interop_dll_path

clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.Core.dll"))
clr.AddReference(interop_dll_path("Microsoft.Web.WebView2.WinForms.dll"))
from Microsoft.Web.WebView2.WinForms import CoreWebView2CreationProperties, WebView2


PAGE_ERRORS = """(function(){var e=window.__pivenErrors=[];
window.addEventListener('error',function(v){var t=v.target;if(t&&t!==window&&(t.src||t.href)){e.push('Failed to load '+(t.src||t.href));}else{e.push((v.message||'Error')+' at '+String(v.filename||'').split('/').pop()+':'+v.lineno);}},true);
window.addEventListener('unhandledrejection',function(v){e.push('Unhandled promise rejection: '+(v.reason&&v.reason.message||v.reason));});
var c=console.error;console.error=function(){e.push('console.error: '+[].map.call(arguments,String).join(' '));return c.apply(console,arguments);};
window.press=function(key){var code=key.length===1?'Key'+key.toUpperCase():key;['keydown','keyup'].forEach(function(type){var ev=new KeyboardEvent(type,{key:key,code:code,bubbles:true,cancelable:true});(document.activeElement||document.body).dispatchEvent(ev);});};
var at={x:0,y:0},locked=null;
Object.defineProperty(Document.prototype,'pointerLockElement',{configurable:true,get:function(){return locked;}});
Element.prototype.requestPointerLock=function(){locked=this;document.dispatchEvent(new Event('pointerlockchange'));return Promise.resolve();};
Document.prototype.exitPointerLock=function(){locked=null;document.dispatchEvent(new Event('pointerlockchange'));};
function spot(v,size){return v>0&&v<=1?v*size:v;}
function under(x,y){return locked||document.elementFromPoint(x,y)||document.body;}
function name(el){return el.tagName.toLowerCase()+(el.id?'#'+el.id:'');}
function fire(el,kind,x,y,b,held,move){var init={bubbles:true,cancelable:true,composed:true,view:window,clientX:x,clientY:y,button:b,buttons:held,movementX:move?move[0]:0,movementY:move?move[1]:0};
if(kind!=='click'&&kind!=='auxclick'&&kind!=='contextmenu'){el.dispatchEvent(new PointerEvent('pointer'+kind,init));el.dispatchEvent(new MouseEvent('mouse'+kind,init));}else{el.dispatchEvent(new MouseEvent(kind,init));}}
function press3(el,x,y,b){var held=b===2?2:b===1?4:1;at={x:x,y:y};fire(el,'move',x,y,0,0);fire(el,'down',x,y,b,held);if(el.focus){el.focus();}fire(el,'up',x,y,b,0);fire(el,b===2?'contextmenu':b===1?'auxclick':'click',x,y,b,0);}
function which(button){return button==='right'?2:button==='middle'?1:0;}
window.click=function(selector,button){var el=document.querySelector(selector);if(!el){return 'nothing matches '+selector;}var r=el.getBoundingClientRect();press3(el,r.left+r.width/2,r.top+r.height/2,which(button));return 'clicked '+name(el);};
window.clickAt=function(x,y,button){x=spot(x,innerWidth);y=spot(y,innerHeight);var el=under(x,y);press3(el,x,y,which(button));return 'clicked '+name(el)+' at '+Math.round(x)+','+Math.round(y);};
window.moveMouse=function(dx,dy){at={x:locked?at.x:at.x+dx,y:locked?at.y:at.y+dy};var el=under(at.x,at.y);fire(el,'move',at.x,at.y,0,0,[dx,dy]);return 'moved over '+name(el);};
window.drag=function(x1,y1,x2,y2,button){x1=spot(x1,innerWidth);y1=spot(y1,innerHeight);x2=spot(x2,innerWidth);y2=spot(y2,innerHeight);var b=which(button),held=b===2?2:b===1?4:1,el=under(x1,y1),steps=5,i;fire(el,'move',x1,y1,0,0);fire(el,'down',x1,y1,b,held);
for(i=1;i<=steps;i++){fire(el,'move',x1+(x2-x1)*i/steps,y1+(y2-y1)*i/steps,b,held,[(x2-x1)/steps,(y2-y1)/steps]);}fire(el,'up',x2,y2,b,0);at={x:x2,y:y2};return 'dragged from '+name(el);};})();"""
PAGE_PICTURE = """(function(){var c=document.querySelector('canvas');if(!c){return '';}try{return c.toDataURL('image/jpeg',0.3).length+':'+c.toDataURL('image/jpeg',0.3).slice(-60);}catch(x){return '';}})()"""

# Click-through helpers: next control, page fingerprint, press.
PAGE_NEXT_CLICK = """(function(){if(document.exitPointerLock){document.exitPointerLock();}
var done=window.__pivenDone=window.__pivenDone||{};
var sel='button,a[href],input,select,summary,[role=button],[onclick],[tabindex],label';
var all=document.querySelectorAll('*'),late=null;
for(var i=0;i<all.length;i++){var e=all[i];var cs=getComputedStyle(e);
if(!(e.matches(sel)||cs.cursor==='pointer')){continue;}
if(e.tagName==='INPUT'&&/^(hidden|text|password|search|email|number|url|tel)$/.test(e.type)){continue;}
if(e.tagName==='LABEL'&&e.control){continue;}
var r=e.getBoundingClientRect();
if(r.width<4||r.height<4||cs.visibility==='hidden'||cs.display==='none'||e.closest('[data-piven-click]')){continue;}
if(e.tagName==='A'){var h=e.getAttribute('href')||'';if(h&&h.charAt(0)!=='#'&&!/^javascript:/i.test(h)){continue;}}
var label=(e.innerText||e.value||e.getAttribute('aria-label')||e.title||'').replace(/\\s+/g,' ').trim().slice(0,40);
var key=e.id?e.tagName+'#'+e.id:e.tagName+'.'+(typeof e.className==='string'?e.className:'')+'|'+label+'|'+Math.round(r.left/20)+','+Math.round(r.top/20);
if(done[key]){continue;}
var hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2),under=hit&&hit!==e&&!e.contains(hit)&&!hit.contains(e);
if(under){if(!late){late={e:e,key:key,label:label};}continue;}
return take(e,key,label);}
if(late){return take(late.e,late.key,late.label);}
return '';
function take(e,key,label){done[key]=1;e.setAttribute('data-piven-click','1');return JSON.stringify({label:label,name:e.tagName.toLowerCase()+(e.id?'#'+e.id:'')});}})()"""
# Fingerprint of what is visible. Before ||| is the layout; after it, what a running page changes by itself.
PAGE_SIGNATURE = """(function(){var els=document.getElementsByTagName('*'),h=0,i,j,k,r,s,e;
function mix(t){for(j=0;j<t.length;j++){h=(h*31+t.charCodeAt(j))|0;}}
for(i=0;i<els.length&&i<2000;i++){e=els[i];r=e.getBoundingClientRect();s=getComputedStyle(e);
if(s.display==='none'||r.width===0||r.height===0){continue;}
mix(e.tagName+Math.round(r.left)+','+Math.round(r.top)+','+Math.round(r.width)+','+Math.round(r.height)+s.visibility+s.opacity+s.backgroundColor+s.color+(e.checked?1:0));}
for(i=1;i<5;i++){for(k=1;k<5;k++){e=document.elementFromPoint(innerWidth*i/5,innerHeight*k/5);mix(e?e.tagName+e.id:'-');}}
var g='';try{var o=window.game||{};Object.keys(o).slice(0,60).forEach(function(n){var t=typeof o[n];if(t==='number'||t==='string'||t==='boolean'){g+=n+'='+o[n]+';';}});}catch(x){}
var c=document.querySelector('canvas'),p='';try{if(c){p=c.toDataURL('image/jpeg',0.2);p=p.length+p.slice(-40);}}catch(x){}
return h+':'+location.href+'|||'+(document.body?document.body.innerText:'')+g+p;})()"""
PAGE_CLICK = """(function(){var e=document.querySelector('[data-piven-click]');if(!e){return '{}';}e.removeAttribute('data-piven-click');
if(e.scrollIntoView){e.scrollIntoView({block:'center',inline:'center'});}
var r=e.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);
var covered=hit&&hit!==e&&!e.contains(hit)&&!hit.contains(e)?hit.tagName.toLowerCase()+(hit.id?'#'+hit.id:''):'';
var off=!!e.disabled;window.clickAt(x,y,'left');
return JSON.stringify({covered:covered,disabled:off});})()"""


PAGE_PROBE = """(function(){var c=[].slice.call(document.querySelectorAll('canvas')).map(function(e){var blank=true;try{var g=e.getContext('2d');if(g&&e.width&&e.height){var d=g.getImageData(0,0,e.width,e.height).data;var first=d[0]+','+d[1]+','+d[2]+','+d[3];for(var i=0;i<d.length;i+=4*3){if(d[i]+','+d[i+1]+','+d[i+2]+','+d[i+3]!==first){blank=false;break;}}}else{blank=null;}}catch(x){blank=null;}return {width:e.width,height:e.height,blank:blank};});return JSON.stringify({title:document.title,text:(document.body?document.body.innerText:'').slice(0,800),elements:document.querySelectorAll('body *').length,canvases:c,size:[document.documentElement.scrollWidth,document.documentElement.scrollHeight]});})()"""


def _is_web(url):
    lowered = str(url or "").lower()
    return lowered.startswith("http://") or lowered.startswith("https://") or lowered == "about:blank"


class NativeBrowser:
    def __init__(self, window, profile_dir):
        self._window = window
        self._profile_dir = profile_dir
        self._control = None
        self._ready = False
        self._watching = False
        self._pending_url = ""
        self._lock = threading.Lock()
        self._state = {"url": "", "title": "", "loading": False, "canBack": False, "canForward": False, "notice": ""}

    def _form(self):
        from webview.platforms.winforms import BrowserView
        return BrowserView.instances.get(self._window.uid)

    def _on_ui(self, action):
        form = self._form()
        if form is None:
            return
        def run():
            action()
        form.Invoke(Func[Type](run))

    def _update(self, **values):
        with self._lock:
            self._state.update(values)

    def _sync_history(self):
        core = self._control.CoreWebView2 if self._control else None
        if core is not None:
            self._update(url=str(core.Source), title=str(core.DocumentTitle), canBack=bool(core.CanGoBack), canForward=bool(core.CanGoForward))

    def _create(self):
        control = WebView2()
        props = CoreWebView2CreationProperties()
        props.UserDataFolder = self._profile_dir
        control.CreationProperties = props
        control.Visible = False
        control.CoreWebView2InitializationCompleted += self._on_ready
        form = self._form()
        form.Controls.Add(control)
        control.BringToFront()
        self._control = control
        control.EnsureCoreWebView2Async(None)

    def _on_ready(self, sender, args):
        if not args.IsSuccess:
            self._update(notice=f"Браузер не запустился: {args.InitializationException}")
            return
        core = sender.CoreWebView2
        settings = core.Settings
        settings.IsWebMessageEnabled = False
        settings.AreHostObjectsAllowed = False
        settings.AreDevToolsEnabled = False
        settings.IsStatusBarEnabled = False
        settings.AreDefaultContextMenusEnabled = True
        core.NavigationStarting += self._on_navigation_starting
        core.NavigationCompleted += self._on_navigation_completed
        core.SourceChanged += lambda *_: self._sync_history()
        core.HistoryChanged += lambda *_: self._sync_history()
        core.DocumentTitleChanged += lambda *_: self._sync_history()
        core.NewWindowRequested += self._on_new_window
        core.DownloadStarting += self._on_download
        self._ready = True
        if self._pending_url:
            core.Navigate(self._pending_url)
            self._pending_url = ""

    def _on_navigation_starting(self, _sender, args):
        if not _is_web(args.Uri):
            args.Cancel = True
            self._update(notice="Во встроенном браузере открываются только сайты (http и https).")
            return
        self._update(loading=True, url=str(args.Uri), notice="")

    def _on_navigation_completed(self, _sender, _args):
        self._update(loading=False)
        self._sync_history()

    def _on_new_window(self, _sender, args):
        args.Handled = True
        if _is_web(args.Uri):
            self._control.CoreWebView2.Navigate(args.Uri)

    def _on_download(self, _sender, args):
        args.Cancel = True
        self._update(notice="Скачивание из встроенного браузера отключено. Открой сайт в обычном браузере, если нужен файл.")

    def place(self, x, y, width, height, visible):
        def action():
            if self._control is None:
                if not visible:
                    return
                self._create()
            self._control.SetBounds(int(x), int(y), max(0, int(width)), max(0, int(height)))
            self._control.Visible = bool(visible) and width > 0 and height > 0
            if self._control.Visible:
                self._control.BringToFront()
        self._on_ui(action)

    def start_offscreen(self):
        """Offscreen control: renders pages but is never shown."""
        def action():
            if self._control is None:
                self._create()
            self._control.SetBounds(-4000, 0, 1280, 900)
            self._control.Visible = True
        self._on_ui(action)

    def navigate(self, url):
        if not _is_web(url):
            return False
        def action():
            if self._ready:
                self._control.CoreWebView2.Navigate(url)
            else:
                self._pending_url = url
        self._on_ui(action)
        return True

    def command(self, name):
        def action():
            core = self._control.CoreWebView2 if self._control and self._ready else None
            if core is None:
                return
            if name == "back" and core.CanGoBack:
                core.GoBack()
            elif name == "forward" and core.CanGoForward:
                core.GoForward()
            elif name == "reload":
                core.Reload()
            elif name == "stop":
                core.Stop()
        self._on_ui(action)

    def state(self):
        with self._lock:
            return dict(self._state)

    @property
    def ready(self):
        return self._ready

    def _wait(self, make, timeout):
        box = {}

        def action():
            core = self._control.CoreWebView2 if self._control and self._ready else None
            if core is not None:
                box["task"] = make(core)
        self._on_ui(action)
        task = box.get("task")
        if task is None:
            return None
        deadline = time.monotonic() + timeout
        while not task.IsCompleted:
            if time.monotonic() > deadline:
                raise TimeoutError("страница не ответила")
            time.sleep(0.1)
        if task.IsFaulted:
            raise RuntimeError(str(task.Exception))
        return task

    def run_script(self, code, timeout=20):
        task = self._wait(lambda core: core.ExecuteScriptAsync(code), timeout)
        return None if task is None else json.loads(str(task.Result) or "null")

    def read_text(self, timeout=20):
        return self.run_script("document.body ? document.body.innerText : ''", timeout)

    def watch_page_errors(self):
        """Collects errors from the very start of every page; check_page reads them."""
        if not self._watching:
            self._watching = True
            self._wait(lambda core: core.AddScriptToExecuteOnDocumentCreatedAsync(PAGE_ERRORS), 15)

    def capture(self, timeout=15):
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        from System.IO import MemoryStream
        stream = MemoryStream()
        if self._wait(lambda core: core.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Jpeg, stream), timeout) is None:
            return b""
        return bytes(stream.ToArray())

    def clear_notice(self):
        self._update(notice="")
