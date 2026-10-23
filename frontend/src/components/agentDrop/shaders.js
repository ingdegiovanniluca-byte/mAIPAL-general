/* The agents' drop: GLSL taken unchanged from the "Gocce Agenti" prototype (shape, deformation,
   colour, eyes, glasses, mask, the hard hat's shade). Keep them as they are: the look depends on
   them, and shape() here must match shapeAt() in scene.js. No pow() of a negative base (NaN). */
/* eslint-disable */
const NOISE = `
vec3 mod289(vec3 x){return x-floor(x*(1./289.))*289.;}
vec4 mod289(vec4 x){return x-floor(x*(1./289.))*289.;}
vec4 permute(vec4 x){return mod289(((x*34.)+1.)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1./6.,1./3.); const vec4 D=vec4(0.,.5,1.,2.);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.,i1.z,i2.z,1.))+i.y+vec4(0.,i1.y,i2.y,1.))+i.x+vec4(0.,i1.x,i2.x,1.));
  float n_=.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.+1.; vec4 s1=floor(b1)*2.+1.; vec4 sh=-step(h,vec4(0.));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.); m=m*m;
  return 42.*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

export const VERT = NOISE + `
uniform float uPhase,uAmp,uFreq,uTip,uScale,uHat,uHatY,uClip,uClipY;
varying vec3 vPos;
varying vec3 vN; varying vec3 vV; varying vec3 vObj;
vec3 shape(vec3 p){
  float k=smoothstep(-0.25,1.0,p.y);
  float taper=1.0-uTip*0.9*k*k;
  vec3 q=vec3(p.x*taper,p.y,p.z*taper);
  float up=max(p.y,0.0);
  q.y+=uTip*0.55*up*up*up;
  q.y-=0.14*uTip;
  return q;
}
vec3 deform(vec3 p){
  vec3 q=shape(p);
  float k=smoothstep(0.2,1.0,p.y);
  float n=snoise(p*uFreq+vec3(0.,uPhase,uPhase*.6));
  n+=0.22*snoise(p*uFreq*2.1-vec3(uPhase*.8));
  float hk=uHat*smoothstep(uHatY-0.1,uHatY+0.04,p.y);
  float ck=uClip*smoothstep(uClipY-0.1,uClipY+0.02,p.y);
  q+=p*n*uAmp*(1.0-0.65*k*uTip)*(1.0-0.9*max(hk,ck));
  // la molletta stringe la punta: si appiattisce tra le due ganasce
  q.z*=1.0-0.62*ck; q.x*=1.0-0.1*ck;
  // sotto il caschetto la testa rientra, e le guance si gonfiano appena come se fosse calzato
  float cy=(p.y-uHatY+0.28)*4.5; float cheek=uHat*0.035*exp(-cy*cy);
  q.xz*=(1.0-0.07*hk)*(1.0+cheek);
  return q*uScale;
}
void main(){
  vec3 p=normalize(position);
  vec3 ref=abs(p.y)>0.98?vec3(1.,0.,0.):vec3(0.,1.,0.);
  vec3 t1=normalize(cross(p,ref)); vec3 t2=normalize(cross(p,t1));
  float e=0.012;
  vec3 d=deform(p);
  vec3 d1=deform(normalize(p+t1*e)); vec3 d2=deform(normalize(p+t2*e));
  vec3 n=normalize(cross(d1-d,d2-d));
  if(dot(n,p)<0.) n=-n;
  vObj=p; vPos=d/uScale;
  vN=normalize(normalMatrix*n);
  vec4 mv=modelViewMatrix*vec4(d,1.);
  vV=mv.xyz;
  gl_Position=projectionMatrix*mv;
}`;

export const FRAG = NOISE + `
uniform vec3 uA,uB; uniform float uSwirl,uGlow,uSpec,uShine,uRim,uIrid,uMilk,uMetal,uHue,uBlink,uEyeH,uGlasses,uHat,uHatY,uMask,uShK,uShR;
uniform vec3 uShA,uShB; varying vec3 vPos;
uniform vec2 uLook; uniform vec2 uEyeR; uniform float uCut,uLid;
varying vec3 vN; varying vec3 vV; varying vec3 vObj;
float ell(vec2 q,vec2 c,vec2 r){ float d=length((q-c)/r); float w=fwidth(d)*1.2; return 1.-smoothstep(1.-w,1.+w,d); }
float sdSeg(vec2 p,vec2 a,vec2 b){vec2 pa=p-a,ba=b-a;float h=clamp(dot(pa,ba)/dot(ba,ba),0.,1.);return length(pa-ba*h);}
const vec2 GL=vec2(-0.235,-0.01); const vec2 GRr=vec2(0.235,-0.01); const float GRAD=0.172; const float GW=0.017;
// montatura tonda: due cerchi, ponte ad arco e stanghette che girano sui lati
float sdEll(vec2 p,vec2 r){return (length(p/r)-1.)*min(r.x,r.y);}
float smin(float a,float b,float k){float h=clamp(.5+.5*(b-a)/k,0.,1.);return mix(b,a,h)-k*h*(1.-h);}
vec2 rot(vec2 p,float a){float c=cos(a),s=sin(a);return vec2(c*p.x+s*p.y,-s*p.x+c*p.y);}
// mascherina da supereroe: due ali attorno agli occhi, fori per gli occhi, fascia che gira sui lati
float maskD(vec2 q,float z){
  vec2 l=rot(q-vec2(-.24,0.),-.28), r=rot(q-vec2(.24,0.),.28);
  l.y*=1.+.9*smoothstep(-.05,-.24,l.x); r.y*=1.+.9*smoothstep(.05,.24,r.x);
  float e1=sdEll(l,vec2(.235,.15)), e2=sdEll(r,vec2(.235,.15));
  float d=smin(e1,e2,.12);
  float bd=abs(q.y-.01)-.032; bd=mix(1e3,bd,step(.3,abs(q.x))*step(-.3,z));
  d=smin(d,bd,.06);
  d=max(d,-sdEll(q-vec2(-.23,-.02),vec2(.1,.088)));
  d=max(d,-sdEll(q-vec2(.23,-.02),vec2(.1,.088)));
  return d;
}
float frameD(vec2 q,float z){
  float d=min(abs(length(q-GL)-GRAD),abs(length(q-GRr)-GRAD));
  vec2 bc=vec2(0.,-0.02);
  float br=abs(length(q-bc)-0.1); br=mix(1e3,br,step(abs(q.x),0.072)*step(0.0,q.y-bc.y));
  d=min(d,br);
  float tx=abs(q.x)-(0.235+GRAD-0.004);
  float tp=abs(q.y-0.03-0.09*max(tx,0.))+max(-tx,0.)*4.+GW*0.45;
  tp=mix(1e3,tp,step(-0.1,z)*step(0.,tx+0.02));
  return min(d,tp)-GW;
}
void main(){
  vec3 N=normalize(vN); vec3 V=normalize(-vV);
  float ndv=max(dot(N,V),0.); float fres=1.-ndv;
  vec3 L=normalize(vec3(-0.45,0.75,0.6));
  float g=clamp(vObj.y*0.45+0.5+0.28*snoise(vObj*1.3+vec3(0.,uSwirl,uSwirl*.7)),0.,1.);
  vec3 base=mix(uA,uB,smoothstep(0.,1.,g));
  // iridescenza
  vec3 irid=0.55+0.45*cos(6.2831*(fres*1.1+vec3(0.,.33,.67)+uHue));
  base=mix(base,irid*mix(vec3(1.),base,.35),uIrid*smoothstep(.05,.9,fres));
  float wrap=dot(N,L)*0.5+0.5;
  vec3 col=base*(0.45+0.6*wrap);
  col=mix(col,mix(base,vec3(1.),0.55)*(0.75+0.3*wrap),uMilk*0.6);
  // cromato: riflesso finto di uno studio
  vec3 R=reflect(-V,N);
  float sky=smoothstep(-0.05,0.35,R.y); float hy=(R.y+0.02)*9.; float hor=exp(-hy*hy);
  vec3 env=mix(base*0.15,mix(base,vec3(1.),.75),sky)-hor*0.25;
  env+=smoothstep(.55,.9,R.x)*smoothstep(.0,.4,R.y)*0.6;
  col=mix(col,env,uMetal*(0.55+0.45*fres));
  // nucleo luminoso
  float core=pow(ndv,3.)*uGlow;
  col+=mix(uB,vec3(1.),.45)*core*0.35;
  // bordo
  col+=mix(uA,vec3(1.),.4)*pow(fres,2.6)*uRim*0.9;
  // luce speculare
  vec3 H=normalize(L+V);
  float hatK=1.-uHat*smoothstep(uHatY-0.45,uHatY-0.1,vObj.y);
  col+=vec3(1.)*pow(max(dot(N,H),0.),uShine)*uSpec*hatK;
  vec3 H2=normalize(normalize(vec3(.7,-.2,.5))+V);
  col+=mix(uB,vec3(1.),.5)*pow(max(dot(N,H2),0.),uShine*.5)*uSpec*.25;
  // ombra morbida e luce riflessa del caschetto sulla fronte
  float hs0=uHat*smoothstep(uHatY-0.3,uHatY-0.02,vObj.y);
  col*=1.-0.55*hs0; col+=vec3(.14,.09,0.)*hs0*.5;
  // ombra morbida di molletta o matita sulla superficie
  if(uShK>0.){vec3 pa=vPos-uShA, ba=uShB-uShA; float hh=clamp(dot(pa,ba)/dot(ba,ba),0.,1.); float dd=length(pa-ba*hh);
    col*=1.-uShK*(1.-smoothstep(uShR*.3,uShR,dd));}
  vec2 q0=vObj.xy;
  float zf=smoothstep(-0.35,-0.1,vObj.z);
  float inH=1.;
  if(uMask>0.5){
    float sm=maskD(q0+vec2(-.014,.022),vObj.z);
    col*=1.-.4*(1.-smoothstep(0.,.035,sm))*zf;
    float md=maskD(q0,vObj.z); float aa=fwidth(md)*1.2; float mm=(1.-smoothstep(-aa,aa,md))*zf;
    float edge=1.-smoothstep(0.,.025,-md);
    vec3 mc=vec3(.0,.19,.25)*(.5+.65*max(dot(N,L),0.));
    mc+=vec3(.35,.75,.85)*pow(max(dot(N,H),0.),16.)*.3+vec3(.12,.4,.48)*edge*.45;
    col=mix(col,mc,mm);
    inH=max(1.-smoothstep(-.004,.004,sdEll(q0-vec2(-.23,-.02),vec2(.112,.098))),1.-smoothstep(-.004,.004,sdEll(q0-vec2(.23,-.02),vec2(.112,.098))));
  }
  float fd=1e3, inL=0.;
  if(uGlasses>0.5){
    fd=frameD(q0,vObj.z);
    // ombra della montatura, spostata in basso a destra rispetto alla luce
    float sd=frameD(q0+vec2(-0.016,0.026),vObj.z);
    col*=1.-0.38*(1.-smoothstep(0.,0.03,sd))*zf;
    inL=max(1.-smoothstep(GRAD-0.012,GRAD,length(q0-GL)),1.-smoothstep(GRAD-0.012,GRAD,length(q0-GRr)))*step(0.2,vObj.z);
    col=mix(col,col*1.04+vec3(.035),inL);
  }
  // occhi stilizzati, dipinti sulla superficie: seguono le onde della goccia
  vec2 q=vObj.xy; vec2 lk=uLook*vec2(0.07,0.05)*mix(1.,.6,max(uGlasses,uMask));
  // dietro le lenti gli occhi sembrano un po' più grandi
  if(uGlasses>0.5){ if(length(q-GL)<GRAD) q=GL+(q-GL)/1.13; else if(length(q-GRr)<GRAD) q=GRr+(q-GRr)/1.13; }
  float front=smoothstep(0.25,0.55,vObj.z);
  vec2 r=vec2(uEyeR.x,uEyeR.y*uEyeH*uBlink+0.012);
  vec2 cl=vec2(-0.23,-0.02)+lk, cr=vec2(0.23,-0.02)+lk;
  float eL=ell(q,cl,r), eR=ell(q,cr,r);
  vec2 co=vec2(0.,uCut*uEyeH*uBlink);
  eL*=1.-step(.001,uCut)*ell(q,cl-co,r*vec2(1.2,1.)); eR*=1.-step(.001,uCut)*ell(q,cr-co,r*vec2(1.2,1.));
  float lidY=r.y*(2.*uLid-1.);
  eL*=1.-smoothstep(-.005,.005,q.y-(cl.y+lidY)); eR*=1.-smoothstep(-.005,.005,q.y-(cr.y+lidY));
  float eye=max(eL,eR)*front*mix(1.,inL,uGlasses)*mix(1.,inH,uMask);
  vec3 eyeCol=mix(vec3(0.07,0.03,0.08),uA*0.25,0.35);
  eyeCol+=vec3(1.)*pow(max(dot(N,H),0.),70.)*0.5;
  col=mix(col,eyeCol,eye);
  float hlv=smoothstep(.45,.85,uBlink)*(1.-step(.001,uCut));
  vec2 ho=vec2(uEyeR.x*.33,uEyeR.y*.38*uEyeH*min(uLid*1.4,1.)); float hs=uEyeR.x/.075;
  float hl=max(ell(q,cl+ho,vec2(.026,.03)*hs),ell(q,cr+ho,vec2(.026,.03)*hs));
  float hl2=max(ell(q,cl-ho*.8,vec2(.012,.014)),ell(q,cr-ho*.8,vec2(.012,.014)));
  col=mix(col,vec3(1.),max(hl,hl2*.8)*eye*hlv);
  if(uGlasses>0.5){
    // riflessi sul vetro, sopra gli occhi
    for(int i=0;i<2;i++){
      vec2 c=i==0?GL:GRr; vec2 d=q0-c;
      float s1=dot(d,normalize(vec2(1.,1.)));
      float m1=(1.-smoothstep(0.012,0.022,abs(s1+0.07)))*(1.-smoothstep(GRAD-0.03,GRAD-0.01,length(d)));
      float m2=(1.-smoothstep(0.005,0.011,abs(s1+0.025)))*(1.-smoothstep(GRAD-0.06,GRAD-0.03,length(d)));
      col=mix(col,vec3(1.),(m1*.42+m2*.3)*step(0.2,vObj.z));
    }
    // montatura con volume: luce e riflesso sul bordo
    float aa=fwidth(fd)*1.2;
    float m=(1.-smoothstep(-aa,aa,fd))*zf;
    float tt=clamp(-fd/GW,0.,1.);
    vec2 cc=length(q0-GL)<length(q0-GRr)?GL:GRr;
    vec2 rd=normalize(q0-cc+1e-5); float sgn=sign(length(q0-cc)-GRAD);
    vec3 Nf=normalize(N+vec3(rd*sgn*(1.-tt)*1.1,0.));
    vec3 fc=vec3(.075,.045,.06)*(.6+.6*max(dot(Nf,L),0.));
    fc+=vec3(1.,.9,.8)*pow(max(dot(Nf,H),0.),40.)*.9;
    fc+=mix(uB,vec3(1.),.3)*pow(1.-max(dot(Nf,V),0.),3.)*.25;
    col=mix(col,fc,m);
  }
  gl_FragColor=vec4(col,1.);
}`;
