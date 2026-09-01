import json,glob,os,sys,collections
base=sys.argv[1]
def norm(s): return " ".join(str(s or "").lower().split())
def key(r): return (norm(r.get('player_name') or r.get('pitcher_name')), norm(r.get('prop') or r.get('market')), r.get('market_line'))
rows=[]; st=collections.Counter(); unmatched=collections.Counter()
for f in sorted(glob.glob(os.path.join(base,'bd','*.json'))):
    date=os.path.basename(f)[:-5]
    try:
        w=json.load(open(f,encoding='utf-8'))
        blob=next(iter((w.get('artifacts') or {}).values()),None)
        if blob is None: st['no_artifact']+=1; continue
        d=json.loads(blob)
    except Exception: st['parse_fail']+=1; continue
    games=d.get('games') if isinstance(d.get('games'),dict) else {}
    for pk,gp in games.items():
        settled=[r for r in (gp.get('all_settled_rows') or []) if isinstance(r,dict)]
        mk=gp.get('markets') if isinstance(gp.get('markets'),dict) else {}
        cand=[]
        for k in ('hitterProps','extraHitterProps','pitcherProps','extraPitcherProps','shadowHitterProps','shadowPitcherProps'):
            v=mk.get(k)
            if isinstance(v,list): cand+=[x for x in v if isinstance(x,dict)]
        cidx={}
        for c in cand: cidx.setdefault(key(c),[]).append(c)
        for s in settled:
            if norm(s.get('market'))=='ml': st['ml']+=1; continue
            st['settled_props']+=1
            m=cidx.get(key(s))
            if not m: st['unjoined']+=1; unmatched[norm(s.get('prop') or s.get('market'))]+=1; continue
            c=next((x for x in m if norm(x.get('selection'))==norm(s.get('selection'))), m[0])
            po,pu,mo=c.get('market_prob_over'),c.get('market_prob_under'),c.get('model_prob_over')
            if po is None or pu is None or mo is None: st['no_probs']+=1; continue
            sel,res=norm(s.get('selection')),norm(s.get('result'))
            if sel not in ('over','under') or res not in ('win','loss'): st['bad']+=1; continue
            st['joined']+=1
            rows.append(dict(date=date, player=norm(s.get('player_name') or s.get('pitcher_name')),
                market=norm(s.get('prop') or s.get('market')), line=s.get('market_line'),
                sel=sel, odds=s.get('odds'), result=res,
                went_over=1 if ((res=='win') if sel=='over' else (res=='loss')) else 0,
                tier=norm(s.get('recommendation_tier')), stake=float(s.get('stake_u') or 0),
                profit=float(s.get('profit_u') or 0), mkt_over=float(po), mkt_under=float(pu),
                model_over=float(mo), novig_over=c.get('market_no_vig_prob_over')))
print("=== JOIN AUDIT (graded artifact, both blocks in one file) ===")
for k,v in sorted(st.items()): print(f"  {k:16s} {v}")
print(f"  join rate: {st['joined']}/{st['settled_props']} = {st['joined']/max(1,st['settled_props'])*100:.1f}%")
if unmatched: print("  unjoined by market:",unmatched.most_common(8))
print(f"  dates covered: {len(set(r['date'] for r in rows))}")
json.dump(rows,open(os.path.join(base,'prop_join.json'),'w'))
print("wrote prop_join.json n=",len(rows))
