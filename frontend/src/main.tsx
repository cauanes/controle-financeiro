import React,{useEffect,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Home,Wallet,PanelsTopLeft,ChartNoAxesCombined,Settings2,MessageCircle,LogOut,ChevronDown,Menu,X,ArrowRight,LockKeyhole} from 'lucide-react';
import {api,setHousehold} from './lib/api';
import type {User} from './lib/api';
import {Dashboard} from './features/Dashboard';
import {Transactions} from './features/Transactions';
import {Resources,Invoices} from './features/Resources';
import {Conversation} from './features/Conversation';
import {Imports,Reconciliation} from './features/Imports';
import {Budgets,Recurring,Calendar,Goals} from './features/Planning';
import {Analytics} from './features/Analytics';
import {Settings} from './features/Settings';
import {ErrorBox,Loading} from './components/ui';
import './style.css';
function App(){const [user,setUser]=useState<User|null>(null),[loading,setLoading]=useState(true),[house,setHouse]=useState(''),[path,setPath]=useState(location.pathname),[menu,setMenu]=useState(false);
 useEffect(()=>{api<User>('/auth/me').then(u=>{setUser(u);const selected=sessionStorage.getItem('ff_household');const active=u.households.find(h=>h.id===selected)||u.households[0];if(active){setHouse(active.id);setHousehold(active.id);}}).catch(()=>{}).finally(()=>setLoading(false));const pop=()=>setPath(location.pathname);addEventListener('popstate',pop);return()=>removeEventListener('popstate',pop);},[]);
 function navigate(next:string){history.pushState({},'',next);setPath(next.split('?')[0]);setMenu(false);window.scrollTo(0,0);}
 function choose(id:string){setHouse(id);setHousehold(id);sessionStorage.setItem('ff_household',id);navigate('/');}
 async function logout(){try{await api('/auth/logout','POST');}finally{setUser(null);setHouse('');setHousehold('');sessionStorage.removeItem('ff_household');}}
 if(loading)return <div className="fullscreen-loading"><Loading/></div>;
 if(!user)return <Login onDone={u=>{setUser(u);const active=u.households[0];if(active){setHouse(active.id);setHousehold(active.id);}navigate('/');}}/>;
 const current=user.households.find(h=>h.id===house);
 if(!current)return <div className="fullscreen-loading"><div className="empty"><h2>Sem família disponível</h2><p>Peça a um administrador para vincular sua conta a uma família.</p><button className="secondary" onClick={logout}>Sair</button></div></div>;
 const groups=[{title:'PRINCIPAL',links:[['/','Visão geral',Home],['/conversations','Conversar',MessageCircle]]},{title:'FINANÇAS',links:[['/finances/transactions','Transações',Wallet],['/finances/accounts','Contas',PanelsTopLeft],['/finances/cards','Cartões',PanelsTopLeft],['/finances/imports','Importar',ArrowRight],['/finances/reconciliation','Revisar lançamentos',ArrowRight]]},{title:'PLANEJAMENTO',links:[['/planning/budgets','Orçamento',PanelsTopLeft],['/planning/recurring','Recorrentes',PanelsTopLeft],['/planning/goals','Metas',PanelsTopLeft],['/planning/calendar','Calendário',PanelsTopLeft]]},{title:'ANÁLISES',links:[['/analytics/cashflow','Fluxo de caixa',ChartNoAxesCombined],['/analytics/expenses','Gastos',ChartNoAxesCombined],['/analytics/patrimony','Patrimônio',ChartNoAxesCombined],['/analytics/health','Saúde financeira',ChartNoAxesCombined],['/analytics/forecast','Projeções',ChartNoAxesCombined]]}];
 let content:React.ReactNode;
 if(path==='/')content=<Dashboard navigate={navigate}/>;
 else if(path==='/conversations')content=<Conversation/>;
 else if(path==='/finances/transactions')content=<Transactions navigate={navigate}/>;
 else if(path==='/finances/invoices')content=<Invoices/>;
 else if(path==='/finances/imports')content=<Imports/>;
 else if(path==='/finances/reconciliation')content=<Reconciliation/>;
 else if(path.startsWith('/finances/'))content=<Resources resource={path.split('/')[2]} navigate={navigate}/>;
 else if(path==='/planning/budgets')content=<Budgets/>;
 else if(path==='/planning/recurring')content=<Recurring/>;
 else if(path==='/planning/goals')content=<Goals navigate={navigate}/>;
 else if(path==='/planning/calendar')content=<Calendar/>;
 else if(path.startsWith('/analytics/'))content=<Analytics view={path.split('/')[2]}/>;
 else if(path.startsWith('/settings'))content=<Settings section={path.split('/')[2]||''} navigate={navigate}/>;
 else content=<div className="empty"><h2>Página não encontrada</h2><button className="primary" onClick={()=>navigate('/')}>Voltar ao início</button></div>;
 return <div className="app-shell" key={house}><button className="mobile-menu" onClick={()=>setMenu(!menu)} aria-label="Abrir navegação">{menu?<X/>:<Menu/>}</button><aside className={'sidebar '+(menu?'open':'')}><button className="brand" onClick={()=>navigate('/')}><span className="brand-mark">c</span><span><strong>cacau</strong><small>finanças da família</small></span></button><div className="household-select"><span>FAMÍLIA ATIVA</span><select aria-label="Família ativa" value={house} onChange={e=>choose(e.target.value)}>{user.households.map(h=><option key={h.id} value={h.id}>{h.name}</option>)}</select></div><nav aria-label="Navegação principal">{groups.map(g=><div className="nav-group" key={g.title}><span>{g.title}</span>{g.links.map(([link,label,Icon])=><button key={link as string} className={path===link?'active':''} onClick={()=>navigate(link as string)}><Icon size={18}/>{label as string}</button>)}</div>)}<div className="nav-group"><span>PREFERÊNCIAS</span><button className={path.startsWith('/settings')?'active':''} onClick={()=>navigate('/settings')}><Settings2 size={18}/>Configurações</button></div></nav><div className="sidebar-bottom"><div className="profile-avatar">{user.display_name?.slice(0,1).toUpperCase()}</div><div><strong>{user.display_name}</strong><small>{current.role.toLowerCase()}</small></div><button onClick={logout} aria-label="Sair"><LogOut size={18}/></button></div></aside><main className="main-content"><div className="topbar"><span>Seu espaço financeiro</span><span>{current.name} <span className="topbar-dot"/> Atualizado agora</span></div><div className="content-wrap">{content}</div><footer>cacau · finanças da família <span>Feito para decisões com clareza</span></footer></main></div>;
}
function Login({onDone}:{onDone:(user:User)=>void}){
 const [error,setError]=useState(''),[busy,setBusy]=useState(false),[invitation,setInvitation]=useState(false),[created,setCreated]=useState('');
 async function submit(e:React.FormEvent<HTMLFormElement>){
  e.preventDefault();setBusy(true);setError('');const f=new FormData(e.currentTarget);
  try{
   if(invitation){const result=await api<{tenant:string;email:string}>('/auth/invitations/register','POST',{token:f.get('token'),email:f.get('email'),display_name:f.get('display_name'),password:f.get('password')});setCreated(result.tenant);setInvitation(false);return;}
   await api('/auth/login','POST',{tenant:f.get('tenant'),email:f.get('email'),password:f.get('password')});onDone(await api<User>('/auth/me'));
  }catch(e){setError((e as Error).message);}finally{setBusy(false);}
 }
 return <div className="login-page"><div className="login-story"><span className="brand-mark large">c</span><p className="eyebrow">FINANÇAS COM MAIS SENTIDO</p><h1>Cuide do que importa.<br/><em>O resto a gente organiza.</em></h1><p>Suas contas, planos e conversas em um só lugar, com cada detalhe financeiro confirmado por você.</p><div className="login-decor"><span>01 / clareza</span><span>02 / cuidado</span><span>03 / futuro</span></div></div><div className="login-form-side"><form className="login-card" onSubmit={submit}><div className="login-lock"><LockKeyhole size={22}/></div><h2>{invitation?'Entrar com convite':'Bem-vindo de volta'}</h2><p>{invitation?'Crie seu acesso para participar das finanças da família.':'Acesse o espaço financeiro da sua família.'}</p><ErrorBox message={error}/>{created&&!invitation&&<p>Cadastro concluído. Identificador da família: <strong>{created}</strong></p>}{invitation?<><label>Código do convite<input name="token" required minLength={16}/></label><label>Seu nome<input name="display_name" required/></label></>:<label>Identificador da família<input name="tenant" autoComplete="organization" placeholder="ex.: minha-familia" required defaultValue={created}/></label>}<label>E-mail<input name="email" type="email" autoComplete="email" placeholder="voce@exemplo.com" required/></label><label>Senha<input name="password" type="password" autoComplete={invitation?'new-password':'current-password'} minLength={invitation?12:undefined} required/></label><button className="primary" disabled={busy}>{busy?'Aguarde…':invitation?'Criar acesso':'Entrar no Cacau'}<ArrowRight size={18}/></button><button type="button" className="text-button" onClick={()=>{setInvitation(!invitation);setError('');}}>{invitation?'Já tenho acesso':'Recebi um convite'}</button><small>O acesso inicial é criado pelo administrador da instalação.</small></form></div></div>;
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
