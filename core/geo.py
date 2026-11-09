# Author: gorcoding
import re
# ISO: (name, typical UTC offset, tolerance, aliases)
_C = {
 "US":("United States",-6,3.5,"united states,usa,u.s.,america,new york,california,texas,florida,los angeles,chicago,washington dc"),
 "GB":("United Kingdom",0,0,"united kingdom,uk,england,london,scotland,wales,britain,manchester"),
 "CA":("Canada",-5,3.5,"canada,toronto,vancouver,ontario,montreal"),
 "AU":("Australia",10,3,"australia,sydney,melbourne,brisbane"),
 "NZ":("New Zealand",12,0,"new zealand,auckland"),"IE":("Ireland",0,0,"ireland,dublin"),
 "IN":("India",5.5,0,"india,bharat,mumbai,delhi,bengaluru,bangalore,hyderabad,kolkata,chennai,pune"),
 "PK":("Pakistan",5,0,"pakistan,karachi,lahore,islamabad"),"BD":("Bangladesh",6,0,"bangladesh,dhaka"),
 "LK":("Sri Lanka",5.5,0,"sri lanka,colombo"),"NP":("Nepal",5.75,0,"nepal,kathmandu"),
 "CN":("China",8,0,"china,beijing,shanghai,shenzhen"),"JP":("Japan",9,0,"japan,tokyo,osaka"),
 "KR":("South Korea",9,0,"south korea,korea,seoul"),"ID":("Indonesia",7,2.5,"indonesia,jakarta"),
 "PH":("Philippines",8,0,"philippines,manila"),"MY":("Malaysia",8,0,"malaysia,kuala lumpur"),
 "SG":("Singapore",8,0,"singapore"),"TH":("Thailand",7,0,"thailand,bangkok"),"VN":("Vietnam",7,0,"vietnam,hanoi"),
 "TR":("Turkey",3,0,"turkey,türkiye,turkiye,istanbul,ankara"),"SA":("Saudi Arabia",3,0,"saudi,riyadh,jeddah"),
 "AE":("UAE",4,0,"uae,dubai,abu dhabi,emirates"),"QA":("Qatar",3,0,"qatar,doha"),"KW":("Kuwait",3,0,"kuwait"),
 "IR":("Iran",3.5,0,"iran,tehran"),"IQ":("Iraq",3,0,"iraq,baghdad"),"IL":("Israel",2,0,"israel,tel aviv,jerusalem"),
 "PS":("Palestine",2,0,"palestine,gaza,west bank"),"EG":("Egypt",2,0,"egypt,cairo"),
 "NG":("Nigeria",1,0,"nigeria,lagos,abuja"),"ZA":("South Africa",2,0,"south africa,johannesburg,cape town"),
 "KE":("Kenya",3,0,"kenya,nairobi"),"DE":("Germany",1,0,"germany,deutschland,berlin,munich"),
 "FR":("France",1,0,"france,paris"),"ES":("Spain",1,0,"spain,españa,madrid,barcelona"),
 "IT":("Italy",1,0,"italy,italia,rome,milan"),"NL":("Netherlands",1,0,"netherlands,amsterdam,holland"),
 "BE":("Belgium",1,0,"belgium,brussels"),"SE":("Sweden",1,0,"sweden,stockholm"),"NO":("Norway",1,0,"norway,oslo"),
 "DK":("Denmark",1,0,"denmark,copenhagen"),"FI":("Finland",2,0,"finland,helsinki"),"PL":("Poland",1,0,"poland,warsaw"),
 "RU":("Russia",4,4.5,"russia,moscow,st petersburg"),"UA":("Ukraine",2,0,"ukraine,kyiv,kiev"),
 "BR":("Brazil",-3,2.5,"brazil,brasil,sao paulo,são paulo,rio"),"MX":("Mexico",-6,2,"mexico,méxico"),
 "AR":("Argentina",-3,0,"argentina,buenos aires"),"CO":("Colombia",-5,0,"colombia,bogota"),
 "CH":("Switzerland",1,0,"switzerland,zurich"),"AT":("Austria",1,0,"austria,vienna"),"PT":("Portugal",0,0,"portugal,lisbon"),
 "GR":("Greece",2,0,"greece,athens"),"RO":("Romania",2,0,"romania,bucharest"),"HU":("Hungary",1,0,"hungary,budapest"),
}
COUNTRIES = {k:{"name":v[0],"off":v[1],"tol":max(v[2],2.5),"al":v[3].split(",")} for k,v in _C.items()}
_RX = {k:re.compile(r"(?<!\w)(?:"+"|".join(re.escape(a) for a in c["al"])+r")(?!\w)") for k,c in COUNTRIES.items()}

def flag_code(t):
    cps=[ord(c)-0x1F1E6 for c in t or "" if 0x1F1E6<=ord(c)<=0x1F1FF]
    for i in range(0,len(cps)-1,2):
        code=chr(65+cps[i])+chr(65+cps[i+1])
        if code in COUNTRIES: return code
    return None

def country_of(text):
    if not text: return None
    f=flag_code(text)
    if f: return f
    low=text.lower()
    for k,rx in _RX.items():
        if rx.search(low): return k
    return None

def parse_country(s):
    """user-typed value: ISO code or country name"""
    s=(s or "").strip()
    if s.upper() in COUNTRIES: return s.upper()
    return country_of(s)

def tld_country(domain):
    t=domain.lower().rstrip(".").split(".")[-1]
    if t=="uk": return "GB"
    return t.upper() if t.upper() in COUNTRIES else None

def tz_candidates(off):
    r=[(abs(((c["off"]-off+12)%24)-12),k) for k,c in COUNTRIES.items()]
    return [k for d,k in sorted(r) if d<=1.0][:6]
