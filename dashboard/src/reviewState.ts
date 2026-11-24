// Evidence receipts bind exact claim paths and values. Never retarget implicitly.
export type FieldIssue={path:string;message:string};
export function valueAt(value:any,path:string):any{
 try{return path.slice(1).split('/').reduce((v,k)=>v[k],value)}catch{return undefined}
}
export function retainedEvidence(previous:any,next:any,receipts:string[]){
 const evidence:any[]=[],retained:string[]=[],invalidated:any[]=[];
 previous.evidence.forEach((entry:any,index:number)=>{
  const event=entry.target.match(/^\/events\/(\d+)\//);
  const sameEvent=!event||previous.events[Number(event[1])]?.instance_id===next.events[Number(event[1])]?.instance_id;
  const oldValue=valueAt(previous,entry.target),newValue=valueAt(next,entry.target);
  if(sameEvent&&newValue!==undefined&&JSON.stringify(oldValue)===JSON.stringify(newValue)){
   evidence.push(entry);retained.push(receipts[index]);
  }else invalidated.push({evidence:entry,receipt_id:receipts[index],reason:'Claim path/value changed; explicit remapping required.'});
 });
 return {evidence,receipts:retained,invalidated};
}
export function formFingerprint(record:string|undefined,annotation:any,receipts:string[],supersedes:string|null){
 return JSON.stringify([record,annotation,receipts,supersedes]);
}
export function utf16Offset(text:string,codepoints:number){return Array.from(text).slice(0,codepoints).join('').length;}
