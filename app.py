import os,re,sqlite3
from datetime import datetime
import requests
from flask import Flask,request,jsonify

BOT_TOKEN=os.environ.get('TELEGRAM_BOT_TOKEN','').strip()
DB_PATH=os.environ.get('DB_PATH','customer_agent.db')
API=f'https://api.telegram.org/bot{BOT_TOKEN}'
app=Flask(__name__)
SESSIONS={}

PRODUCTS={'الجهاز':{'price':30.0,'currency':'$','available':True},'منتج تجريبي':{'price':30.0,'currency':'$','available':True}}
DELIVERY={'حلب':'2-3 أيام','دمشق':'3-5 أيام','حمص':'2-4 أيام','اللاذقية':'2-4 أيام'}
CITIES=['ريف دمشق','أشرفية صحنايا','معضمية الشام','دير عطية','رأس العين','جسر الشغور','معرة النعمان','معرة مصرين','بصرى الشام','تل أبيض','خان أرنبة','عين العرب','تل رفعت','قلعة المضيق','طيبة الإمام','دمشق','دوما','حرستا','عربين','سقبا','حمورية','زملكا','جرمانا','صحنايا','داريا','قدسيا','الهامة','التل','يبرود','النبك','القطيفة','الزبداني','مضايا','بلودان','قطنا','الكسوة','حلب','منبج','الباب','اعزاز','أعزاز','عفرين','جرابلس','السفيرة','دير حافر','مسكنة','كوباني','مارع','الاتارب','الأتارب','حمص','تدمر','الرستن','تلبيسة','القصير','تلكلخ','المخرم','القريتين','الحولة','حماة','سلمية','مصياف','محردة','السقيلبية','صوران','كفرزيتا','اللاذقية','جبلة','القرداحة','الحفة','كسب','طرطوس','بانياس','صافيتا','الدريكيش','الشيخ بدر','القدموس','إدلب','أريحا','اريحا','سراقب','بنش','سرمين','الدانا','كفرنبل','الحسكة','القامشلي','المالكية','ديريك','راس العين','عامودا','الدرباسية','الشدادي','تل تمر','القحطانية','اليعربية','الرقة','الطبقة','تل ابيض','معدان','المنصورة','دير الزور','الميادين','البوكمال','العشارة','القورية','موحسن','درعا','نوى','الصنمين','طفس','جاسم','ازرع','إزرع','داعل','الحراك','السويداء','شهبا','صلخد','القريا','القنيطرة','خان ارنبة','البعث']

def norm(s):
    s=str(s or '').strip().lower()
    for a,b in {'أ':'ا','إ':'ا','آ':'ا','ة':'ه','ى':'ي'}.items(): s=s.replace(a,b)
    return re.sub(r'\s+',' ',re.sub(r'[^\w\s\u0600-\u06FF]',' ',s)).strip()

def init_db():
    c=sqlite3.connect(DB_PATH)
    c.execute('''CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,customer_name TEXT,customer_phone TEXT,product_name TEXT,quantity INTEGER,price REAL,currency TEXT,country TEXT,city TEXT,status TEXT DEFAULT 'new',customer_message TEXT,created_at TEXT)''')
    c.commit();c.close()

def session(cid):
    return SESSIONS.setdefault(str(cid),{'name':None,'phone':None,'city':None,'product':None,'qty':1,'buying':False,'done':False,'order_id':None})

def reset(cid): SESSIONS.pop(str(cid),None)

def detect_phone(text):
    m=re.search(r'(?<!\d)(\+?\d[\d\s\-]{6,16}\d)(?!\d)',str(text))
    if not m:return None
    p=re.sub(r'[^\d+]','',m.group(1))
    return p if len(re.sub(r'\D','',p))>=8 else None

def detect_city(text):
    n=norm(text)
    for x in sorted(CITIES,key=lambda z:len(norm(z)),reverse=True):
        if norm(x) in n:return x
    return None

def detect_product(text):
    n=norm(text);matches=[]
    for name,p in PRODUCTS.items():
        nn=norm(name);variants={nn}
        if nn.startswith('ال') and len(nn)>3:variants.add(nn[2:])
        if any(v in n for v in variants):matches.append((name,p))
    return matches[0] if len(matches)==1 else None

def detect_quantity(text):
    n=norm(text);m=re.search(r'\b(\d+)\b',n)
    if m and int(m.group(1))>0:return int(m.group(1))
    mp={'جهازين':2,'قطعتين':2,'منتجين':2,'اثنين':2,'اتنين':2,'ثلاث':3,'ثلاثه':3,'اربع':4,'اربعه':4,'خمس':5,'خمسه':5}
    for k,v in mp.items():
        if norm(k) in n:return v
    return 1

def explicit_name(text):
    m=re.search(r'(?:اسمي|الاسم)\s*[:\-]?\s*([\u0600-\u06FF]{2,20}(?:\s+[\u0600-\u06FF]{2,20})?)',str(text))
    return m.group(1).strip() if m else None

def is_buy(text):
    n=norm(text)
    return any(norm(k) in n for k in ['بدي اشتري','اريد شراء','بدي اخد','حابب اشتري','حابه اشتري','حاب اشتري','بدي اطلب','اريد الطلب','يلزمني','بدي جهاز','بدي منتج'])

def create_order(s,text):
    p=PRODUCTS[s['product']];c=sqlite3.connect(DB_PATH)
    cur=c.execute('''INSERT INTO orders(customer_name,customer_phone,product_name,quantity,price,currency,country,city,status,customer_message,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(s['name'],s['phone'],s['product'],s['qty'],p['price'],p['currency'],'سوريا',s['city'],'new',text,datetime.now().isoformat(timespec='seconds')))
    oid=cur.lastrowid;c.commit();c.close();return oid

def reply(cid,text):
    s=session(cid);text=str(text or '').strip()
    if not text:return 'اكتبلي رسالتك حتى أساعدك.'
    ph=detect_phone(text);ct=detect_city(text);pr=detect_product(text);nm=explicit_name(text)
    if ph:s['phone']=ph
    if ct:s['city']=ct
    if pr:s['product']=pr[0]
    if nm:s['name']=nm
    if is_buy(text):s['buying']=True;s['qty']=detect_quantity(text)
    n=norm(text)
    if any(k in n for k in ['سعر','بكم','قديش','حق']) and not s['buying']:
        if pr:
            price=int(pr[1]['price']) if float(pr[1]['price']).is_integer() else pr[1]['price']
            return f"سعر {pr[0]} هو {price}{pr[1]['currency']} ✅"
        return 'أي منتج حابب تعرف سعره؟'
    if any(k in n for k in ['توصيل','شحن']) and not s['buying']:
        return f"التوصيل إلى {ct}: {DELIVERY.get(ct,'2-4 أيام')} 🚚" if ct else 'قلي لأي مدينة حتى أعطيك مدة التوصيل.'
    if not s['buying']:
        if any(k in n for k in ['مرحبا','اهلا','هلا','السلام عليكم']):return 'أهلاً وسهلاً 👋 اسألني عن المنتجات أو الأسعار أو التوصيل، أو اطلب مباشرة.'
        return 'تفضل 👋 فيني أساعدك بالسعر، المنتج، التوصيل أو تسجيل طلب.'
    if not s['product']:return 'تمام 👍 شو المنتج اللي بدك تطلبه؟'
    if not s['name']:
        if not ph and not ct and not is_buy(text):
            words=norm(text).split()
            if 1<=len(words)<=3 and all(re.fullmatch(r'[\u0600-\u06FF]+',w) for w in words):s['name']=text.strip()
            else:return 'تمام 👍 شو اسمك حتى أسجل الطلب؟'
        else:return 'تمام 👍 شو اسمك حتى أسجل الطلب؟'
    if not s['phone']:return f"تمام {s['name']} 👍 ابعتلي رقم الهاتف."
    if not s['city']:return 'ممتاز 👍 بقي بس أعرف المدينة.'
    if s['done']:return f"طلبك مسجل مسبقاً ✅ رقم الطلب: {s['order_id']}"
    oid=create_order(s,text);s['done']=True;s['order_id']=oid
    p=PRODUCTS[s['product']];total=p['price']*s['qty'];total=int(total) if float(total).is_integer() else total
    return f"✅ تم تسجيل طلبك\nرقم الطلب: {oid}\nالاسم: {s['name']}\nالمنتج: {s['product']}\nالكمية: {s['qty']}\nالإجمالي: {total}{p['currency']}\nالمدينة: {s['city']}\nالتوصيل: {DELIVERY.get(s['city'],'2-4 أيام')}"

def tg(method,**data):
    r=requests.post(f'{API}/{method}',json=data,timeout=20);r.raise_for_status();return r.json()

@app.get('/')
def health(): return jsonify({'status':'ok'})

@app.post('/telegram')
def telegram_webhook():
    update=request.get_json(silent=True) or {};msg=update.get('message',{});text=msg.get('text');cid=msg.get('chat',{}).get('id')
    if not text or cid is None:return jsonify({'ok':True})
    if text=='/start':ans='أهلاً وسهلاً 👋\nأنا مساعد المتجر.\nاسألني عن المنتجات أو الأسعار أو التوصيل، أو اطلب مباشرة.'
    elif text=='/reset':reset(cid);ans='✅ تم بدء محادثة جديدة.'
    else:ans=reply(cid,text)
    tg('sendMessage',chat_id=cid,text=ans)
    return jsonify({'ok':True})

init_db()

# Register Telegram webhook automatically whenever the service starts.
if BOT_TOKEN and WEBHOOK_URL:
    try:
        requests.post(
            f"{API}/setWebhook",
            json={"url": WEBHOOK_URL, "drop_pending_updates": True},
            timeout=20
        ).raise_for_status()
        print("Telegram webhook registered")
    except Exception as e:
        print("Webhook registration failed:", e)
