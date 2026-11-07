import pytest
from analysis.review_app.assess_taxonomy import validate


def test_positive_requires_target_evidence_and_all_modes():
    trace={'blocks':[{'role':'assistant','text':'Your request is pending.'}]}
    rows={'assessments':[{'mode':'example','label':1,'reason':'Specific evidence','quote':'pending','subtypes':[]}]}
    assert validate(rows,['example'],trace)
    rows['assessments'][0]['quote']='processed'
    with pytest.raises(AssertionError):validate(rows,['example'],trace)
    rows['assessments'][0]['label']=None
    assert validate(rows,['example'],trace)
    with pytest.raises(AssertionError):validate(rows,['example','missing'],trace)
