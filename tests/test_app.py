"""Step 7: the Streamlit app renders every job at every replay stage without errors."""
from streamlit.testing.v1 import AppTest

from src.replay import STAGES


def test_app_renders_all_stages_and_jobs():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception
    assert "does not authorize outreach" in at.warning[0].value
    for label, _ in STAGES:
        at.sidebar.radio[0].set_value(label).run()
        for i in range(len(at.selectbox[0].options)):
            at.selectbox[0].select_index(i).run()
            assert not at.exception, at.exception
