"""Browser test against port 42021; does not submit a video job."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

evidence = Path(r'F:\videos_test\evidence\audience')
with sync_playwright() as p:
    browser = p.chromium.launch(channel='chrome', headless=True)
    page = browser.new_page(viewport={'width': 1440, 'height': 1100})
    page.goto('http://127.0.0.1:42021/')
    dropdown = page.get_by_test_id('audience')
    options = dropdown.locator('option').evaluate_all('(els)=>els.map(e=>e.value)')
    assert options == ['', 'common', 'beginner', 'informed', 'expert'], options
    expect(dropdown).to_have_value('')
    dropdown.select_option('beginner')
    expect(dropdown).to_have_value('beginner')
    page.goto('http://127.0.0.1:42021/make')
    choice = page.get_by_test_id('make-audience')
    expect(choice).to_have_value('')
    choice.select_option('beginner')
    frame = page.frame_locator('#form')
    expect(frame.get_by_test_id('audience')).to_have_value('beginner')
    # Stub only the model-backed parse result to avoid an unrelated Ollama call.
    spec = {'input': {'type': 'text', 'source': 'A source passage.', 'title': '', 'credit': ''},
        'output': {'mode': 'smoke', 'short_length': 30, 'long_minutes': 15},
        'pipeline': {'script_review': True, 'captions': True, 'presenter': False,
            'visuals': 'never', 'script_ai': 'deepseek', 'audience': 'beginner'}}
    requests = []
    def parse(route):
        requests.append(route.request.post_data_json)
        route.fulfill(json={'spec': spec, 'summary': ['Audience: Beginner'], 'notes': [], 'parsed_by': 'UI fixture'})
    page.route('**/make/parse', parse)
    page.get_by_test_id('make-describe').fill('Make a 30-second beginner-friendly weather Short')
    page.get_by_test_id('make-generate').click()
    expect(page.get_by_test_id('make-message')).to_contain_text('Form filled')
    assert requests[0]['audience'] == 'beginner'
    expect(frame.get_by_test_id('audience')).to_have_value('beginner')
    page.screenshot(path=str(evidence / 'beginner-ui.png'), full_page=True)
    # Legacy saved specs without an audience still inherit the settings default.
    spec['pipeline'].pop('audience')
    page.evaluate('(s)=>fillForm(s)', spec)
    expect(choice).to_have_value('')
    expect(frame.get_by_test_id('audience')).to_have_value('')
    browser.close()
print('PASS: Common default, Beginner after Common on both forms, /make propagation, legacy saved specs.')
