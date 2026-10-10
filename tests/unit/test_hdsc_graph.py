"""Actual PyTorch CPU arithmetic; run in the qualified AI image, no GPU claim."""
import unittest
from unittest.mock import patch


class GraphAttentionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
            from transformers import GPTNeoConfig, GPTNeoForCausalLM
        except ImportError as error:raise unittest.SkipTest('Requires qualified AI image') from error
        cls.torch=torch;cls.Config=GPTNeoConfig;cls.Model=GPTNeoForCausalLM
        torch.set_num_threads(1)

    def model(self):
        self.torch.manual_seed(82000)
        config=self.Config(vocab_size=64,hidden_size=32,num_heads=4,num_layers=2,
            max_position_embeddings=32,window_size=4,attention_types=[[['global','local'],1]])
        config._attn_implementation='eager'
        return self.Model(config).eval()

    def test_attention_exactly_matches_upstream_including_optional_masks(self):
        from cc_contract.hdsc_graph_attention import install
        model=self.model();torch=self.torch
        layers=[block.attn.attention for block in model.transformer.h]
        originals=[layer._attn for layer in layers]
        weights={k:v.clone() for k,v in model.state_dict().items()}
        receipt=install(model);self.assertEqual(receipt['constant_bytes'],8)
        with torch.inference_mode():
            for layer,original in zip(layers,originals):
                for length in (1,4,16):
                    q,k,v=[torch.randn(1,4,length,8) for _ in range(3)]
                    for optional in (False,True):
                        mask=torch.zeros(1,1,length,length) if optional else None
                        heads=torch.tensor([1.,0.,1.,1.]).view(1,4,1,1) if optional else None
                        if optional:mask[:,:,:,-1]=-1000
                        expected=original(q,k,v,mask,heads)
                        # The adapted compute path must not construct a host scalar tensor.
                        with patch.object(torch,'tensor',side_effect=AssertionError('host tensor during attention')):
                            actual=layer._attn(q,k,v,mask,heads)
                        self.assertTrue(all(torch.equal(a,b) for a,b in zip(actual,expected)))
        self.assertEqual(set(weights),set(model.state_dict()))
        self.assertTrue(all(torch.equal(v,model.state_dict()[k]) for k,v in weights.items()))

    def test_full_logits_exact_and_adapter_refuses_repeat_or_drift(self):
        from cc_contract import hdsc_graph_attention as adapter
        model=self.model();torch=self.torch;tokens=torch.arange(16).view(1,16)
        with torch.inference_mode():expected=model(tokens,use_cache=False).logits.clone()
        adapter.install(model)
        with torch.inference_mode():self.assertTrue(torch.equal(expected,model(tokens,use_cache=False).logits))
        with self.assertRaises(ValueError):adapter.install(model)
        with patch.object(adapter,'UPSTREAM_SHA256','0'*64):
            with self.assertRaises(ValueError):adapter.install(self.model())

    def test_upstream_diagnostic_restores_adapter_after_failure(self):
        from cc_contract import hdsc_graph_attention as adapter
        model=self.model();adapter.install(model)
        layer=model.transformer.h[0].attn.attention;bound=layer._attn
        with self.assertRaisesRegex(RuntimeError,'diagnostic'):
            with adapter.upstream_eager(model):
                self.assertNotEqual(layer._attn,bound)
                raise RuntimeError('diagnostic failed')
        self.assertEqual(layer._attn,bound)


if __name__=='__main__':unittest.main()
