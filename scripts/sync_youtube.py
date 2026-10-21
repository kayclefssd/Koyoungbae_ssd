"""Sync public channel uploads into broadcast.csv; never edit notes/scenes."""
import csv, json, os, re, sys, urllib.parse, urllib.request
from pathlib import Path

API='https://www.googleapis.com/youtube/v3/'
KEY=os.environ.get('YOUTUBE_API_KEY','').strip()
HANDLE=os.environ.get('YOUTUBE_HANDLE','@goransoyoungbae')
CSV=Path('broadcast.csv')
FIELDS=['id','date','type','title','url','description']

def api(endpoint, **params):
    if not KEY: raise RuntimeError('YOUTUBE_API_KEY secret is missing')
    url=API+endpoint+'?'+urllib.parse.urlencode(dict(params,key=KEY))
    try:
        with urllib.request.urlopen(url,timeout=35) as response:
            return json.load(response)
    except urllib.error.HTTPError as err:
        details=err.read().decode('utf-8','replace')[:500]
        raise RuntimeError(f'YouTube API HTTP {err.code}: {details}') from err

def playlist_ids(playlist_id):
    result=set(); token=None
    while True:
        p=dict(part='contentDetails',playlistId=playlist_id,maxResults=50)
        if token: p['pageToken']=token
        data=api('playlistItems',**p)
        result.update(x.get('contentDetails',{}).get('videoId','') for x in data.get('items',[]))
        token=data.get('nextPageToken')
        if not token: break
    result.discard('')
    return result

def duration_seconds(iso):
    m=re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',iso or '')
    return sum(int(x or 0)*scale for x,scale in zip(m.groups(),(86400,3600,60,1))) if m else 0

def read_existing():
    if not CSV.exists(): return []
    with CSV.open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

def main():
    channel=api('channels',part='contentDetails,snippet',forHandle=HANDLE).get('items',[])
    if not channel: raise RuntimeError(f'Channel not found: {HANDLE}')
    channel=channel[0]; cid=channel['id']; uploads=channel['contentDetails']['relatedPlaylists']['uploads']
    ids=playlist_ids(uploads)
    print(f'Channel: {channel["snippet"]["title"]}; uploaded entries: {len(ids)}')
    # YouTube does not provide a documented Shorts flag in Data API v3.
    # This playlist naming convention is unofficial; fall back conservatively.
    shorts=None
    try:
        shorts=playlist_ids('UUSH'+cid[2:])
        print(f'Shorts playlist identified: {len(shorts)}')
    except Exception as exc:
        print(f'WARNING: Shorts playlist unavailable ({exc}); using <=180s heuristic. Short clips may be excluded.',file=sys.stderr)
    video_ids=sorted(ids-(shorts or set()))
    fetched=[]
    for i in range(0,len(video_ids),50):
        data=api('videos',part='snippet,contentDetails,liveStreamingDetails,status',id=','.join(video_ids[i:i+50]))
        fetched.extend(data.get('items',[]))
    fresh={}
    for v in fetched:
        sn=v['snippet']; vid=v['id']; sec=duration_seconds(v.get('contentDetails',{}).get('duration',''))
        if shorts is None and 0<sec<=180: continue
        if v.get('status',{}).get('privacyStatus')!='public': continue
        if sn.get('liveBroadcastContent') in ('upcoming','live'): continue
        if not sn.get('publishedAt'): continue
        typ='LIVE' if v.get('liveStreamingDetails') else 'CLIP'
        fresh[vid]={'id':vid,'date':sn['publishedAt'][:10],'type':typ,'title':sn.get('title',''),
                    'url':'https://www.youtube.com/watch?v='+vid,'description':sn.get('description','')}
    # Keep manually added member/unlisted videos and user-created entries.
    # Never overwrite hand-authored notes or scenes.
    existing=read_existing()
    manual={r['id']:r for r in existing if r.get('id') and not r['id'].startswith('DEMO') and r['id'] not in fresh}
    combined={**manual,**fresh}
    rows=sorted(combined.values(),key=lambda r:(r.get('date',''),r.get('id','')),reverse=True)
    with CSV.open('w',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=FIELDS,extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
    print(f'Saved {len(fresh)} public videos and {len(manual)} previously saved entries to {CSV}')
    print('broadcast-notes.csv and scenes.csv were NOT modified')

if __name__=='__main__':
    try: main()
    except Exception as exc:
        print('ERROR:',exc,file=sys.stderr); sys.exit(1)
