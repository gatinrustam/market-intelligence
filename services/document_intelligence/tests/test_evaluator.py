from app.evaluator import score

def test_precision_recall_counts_occurrences_not_set_membership():
    result=score(['a','a','b'],['a','a','c','d'])
    assert result=={'tp':2,'fp':2,'fn':1,'precision':.5,'recall':2/3,'f1':4/7}

def test_empty_metrics_are_unavailable_not_perfect():
    assert score([],[])=={'tp':0,'fp':0,'fn':0,'precision':None,'recall':None,'f1':None}
