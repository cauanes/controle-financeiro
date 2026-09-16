import {useEffect, useRef} from 'react';
import type {ReactNode} from 'react';
import {ArrowUpRight, Inbox, LoaderCircle, X} from 'lucide-react';
export function Empty({title='Nada por aqui ainda',children}: {title?:string;children?:ReactNode}) {return <div className="empty"><Inbox size={28}/><h3>{title}</h3><p>{children || 'Os registros da sua família aparecerão aqui.'}</p></div>;}
export function ErrorBox({message}: {message:string}) {return message ? <div role="alert" className="error">{message}</div> : null;}
export function Loading() {return <div role="status" className="loading"><LoaderCircle className="spin" size={20}/> Carregando seus dados…</div>;}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:string}) {return <span className={'badge '+tone}>{children}</span>;}
export function Panel({title,description,children,action}:{title:string;description?:string;children:ReactNode;action?:ReactNode}) {return <section className="panel"><div className="panel-heading"><div><h2>{title}</h2>{description&&<p>{description}</p>}</div>{action}</div>{children}</section>;}
export function Modal({title,children,onClose}:{title:string;children:ReactNode;onClose:()=>void}) {
 const ref=useRef<HTMLDialogElement>(null);
 useEffect(()=>{const previous=document.activeElement as HTMLElement;ref.current?.showModal();return()=>previous?.focus();},[]);
 return <dialog ref={ref} onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose();}} aria-label={title}><div className="modal-heading"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="Fechar"><X size={20}/></button></div>{children}</dialog>;
}
export function SectionHeader({title,subtitle,children}:{title:string;subtitle:string;children?:ReactNode}) {return <div className="section-header"><div><div className="eyebrow">SUAS FINANÇAS, COM CLAREZA</div><h1>{title}</h1><p>{subtitle}</p></div><div className="header-actions">{children}</div></div>;}
export function Metric({title,value,note,icon,accent=false}:{title:string;value:string;note:string;icon:ReactNode;accent?:boolean}) {return <div className={'metric '+(accent?'accent':'')}><div className="metric-top"><span>{title}</span>{icon}</div><strong>{value}</strong><p>{note}</p></div>;}
export function ActionLink({children,onClick}:{children:ReactNode;onClick:()=>void}) {return <button className="text-button" onClick={onClick}>{children}<ArrowUpRight size={16}/></button>;}
