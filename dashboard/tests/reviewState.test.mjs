import {test} from 'node:test';
import assert from 'node:assert/strict';
import {transform} from 'esbuild';
import {readFile} from 'node:fs/promises';
const {code}=await transform(await readFile(new URL('../src/reviewState.ts',import.meta.url),'utf8'),{loader:'ts',format:'esm',target:'es2022'});
const {retainedEvidence,formFingerprint,utf16Offset}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const a={domains:['defense','economics','geopolitics'],defense_event_types:['military_technology'],events:[],evidence:[{target:'/domains/0',quote:'fleet'},{target:'/domains/1',quote:'trade'},{target:'/domains/2',quote:'talks'},{target:'/defense_event_types/0',quote:'sensors'}]};
const receipts=['r0','r1','r2','r3'];
test('adding a missing claim preserves every unchanged receipt',()=>{
 const result=retainedEvidence(a,{...a,domains:[...a.domains,'cybersecurity']},receipts);
 assert.deepEqual(result.evidence,a.evidence);assert.deepEqual(result.receipts,receipts);assert.deepEqual(result.invalidated,[]);
});
test('editing rationale cannot erase evidence',()=>assert.deepEqual(retainedEvidence(a,{...a,rationale:'new reasoning'},receipts).receipts,receipts));
test('changed claim paths invalidate only their own receipts',()=>{
 const result=retainedEvidence(a,{...a,domains:['defense','cybersecurity','geopolitics']},receipts);
 assert.deepEqual(result.receipts,['r0','r2','r3']);assert.equal(result.invalidated[0].receipt_id,'r1');
});
test('array reordering never silently retargets saved evidence',()=>{
 const result=retainedEvidence(a,{...a,domains:['economics','defense','geopolitics']},receipts);
 assert.deepEqual(result.receipts,['r2','r3']);assert.equal(result.invalidated.length,2);
});
test('replaced event identity requires fresh human mapping',()=>{
 const previous={...a,events:[{instance_id:'a',domains:['defense']}],evidence:[{target:'/events/0/domains/0'}]};
 assert.equal(retainedEvidence(previous,{...previous,events:[{instance_id:'b',domains:['defense']}]},['receipt']).evidence.length,0);
});
test('source changes and edits have distinct save fingerprints',()=>{
 assert.notEqual(formFingerprint('old',a,receipts,null),formFingerprint('new',a,receipts,null));
 assert.notEqual(formFingerprint('old',a,receipts,null),formFingerprint('old',{...a,rationale:'edit'},receipts,null));
});
test('Unicode remapping preserves codepoint-to-browser offset boundaries',()=>{
 const text='😀 consortium’s fleet';assert.equal(utf16Offset(text,1),2);assert.equal(utf16Offset(text,13),14);
});
