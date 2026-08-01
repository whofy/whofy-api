import requests
import re
import json

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Try to find API endpoints by checking common patterns
api_urls = [
    'https://www.naukri.com/jobapi/v3/search',
    'https://www.naukri.com/jobapi/v2/search',
    'https://www.naukri.com/api/jobs',
    'https://www.naukri.com/middlewave/getJobList',
]

for api_url in api_urls:
    print(f'\nTrying API: {api_url}')
    params = {
        'keyword': 'software engineer',
        'location': 'bengaluru',
        'experience': '-1'
    }
    try:
        r = requests.get(api_url, headers=headers, params=params, timeout=30)
        print(f'Status: {r.status_code}, Length: {len(r.text)}')
        if r.status_code == 200 and len(r.text) > 100:
            print('First 500 chars:', r.text[:500])
            try:
                data = json.loads(r.text)
                print('JSON keys:', list(data.keys()))
                with open(f'naukri_api_{api_url.split("/")[-1]}.json', 'w') as f:
                    json.dump(data, f, indent=2)
            except:
                pass
    except Exception as e:
        print(f'Error: {e}')
