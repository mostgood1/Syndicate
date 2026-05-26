import requests

def main():
    ymd = '20260112'
    gid = '0022500558'
    url = f'https://data.nba.com/data/10s/prod/v1/{ymd}/{gid}_boxscore.json'
    print(url)
    r = requests.get(url, headers={'Accept': 'application/json', 'User-Agent': 'nba-betting/1.0'}, timeout=15)
    print('status', r.status_code, 'len', len(r.content))
    print(r.text[:600])

if __name__ == '__main__':
    main()
