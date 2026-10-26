"""Regression: the delete-manager button must render a VALID onclick.

tojson emits a "..."-quoted string; inside a double-quoted onclick the first " ended the
attribute, so the handler became `deleteManager(5, "` and clicking threw a SyntaxError —
teamleads/heads couldn't delete anyone. The attribute must be single-quoted."""


def test_delete_button_onclick_is_single_quoted(client, login, users):
    login(users['teamlead'])
    html = client.get('/managers/list').get_data(as_text=True)
    assert "onclick='deleteManager(" in html          # single-quoted wrapper (fixed)
    assert 'onclick="deleteManager(' not in html       # the broken double-quoted form
