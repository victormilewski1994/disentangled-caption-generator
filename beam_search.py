"""Beam search implementation in PyTorch."""
#
#
#         hyp1#-hyp1---hyp1 -hyp1
#                 \             /
#         hyp2 \-hyp2 /-hyp2#hyp2
#                               /      \
#         hyp3#-hyp3---hyp3 -hyp3
#         ========================
#
# Takes care of beams, back pointers, and scores.

# Code borrowed from PyTorch OpenNMT example
# https://github.com/pytorch/examples/blob/master/OpenNMT/onmt/Beam.py

import torch


class Beam(object):
    """Ordered beam of candidate outputs."""

    def __init__(self, size, processor, device=torch.device('cuda')):
        """Initialize params."""
        self.size = size
        self.done = False
        self.processor = processor
        self.device = device

        # The score for each translation on the beam.
        self.scores = torch.FloatTensor(size).zero_().to(device)

        # mask for ending advancing finished sequences. -inf if done, 1 otherwise
        self.mask = torch.FloatTensor(size).fill_(1).to(device)

        # The backpointers at each time-step.
        self.prevKs = []

        # The outputs at each time-step.
        self.nextYs = [torch.LongTensor(size).fill_(self.processor.w2i[self.processor.PAD]).to(device)]
        self.nextYs[0][0] = processor.w2i[processor.START]

        # The attentions (matrix) for each time.
        self.attn = []

    def get_current_state(self):
        """Get state of beam for the current time step."""
        return self.nextYs[-1]

    def get_current_origin(self):
        """Get the backpointer to the beam at this step."""
        return self.prevKs[-1]

    def advance(self, word_lk, attn_out=None):
        """
        Given prob over words for every last beam `wordLk` and attention `attnOut`: Compute and update the beam search.
        :param word_lk: probs of advancing from the last step (K x words)
        :param attn_out: attention at the last step
        :return: True if beam search is complete.
        """
        num_words = word_lk.size(1)

        # apply mask over the scores so finished sequences wont get expanded
        word_lk = self.mask.unsqueeze(1).expand_as(word_lk) * word_lk
        # expanding with padding is free if the end of the sentence is reached. This ensures
        # that short sentence can also be predicted
        word_lk[(self.mask < 0).nonzero(), self.processor.w2i[self.processor.PAD]] = 0

        # Sum the previous scores.
        if len(self.prevKs) > 0:
            beam_lk = word_lk + self.scores.unsqueeze(1).expand_as(word_lk)
        else:
            beam_lk = word_lk[0]

        flat_beam_lk = beam_lk.view(-1)

        best_scores, best_scores_id = flat_beam_lk.topk(self.size, dim=0, largest=True, sorted=True)
        self.scores = best_scores

        # best_scores_id is flattened beam x word array, so calculate which
        # word and beam each score came from
        prev_k = best_scores_id / num_words
        self.prevKs.append(prev_k)
        self.nextYs.append(best_scores_id - prev_k * num_words)

        # Update sequence scores and erase scores for EOS and PAD symbols so that they aren't expanded
        # stored_scores.append(best_scores.clone())
        eos_indices = self.nextYs[-1].data.eq(self.processor.w2i[self.processor.END]) + \
                      self.nextYs[-1].data.eq(self.processor.w2i[self.processor.PAD])
        if eos_indices.nonzero().dim() > 1:
            self.mask.fill_(1) # reset mask, finished seq might be dropped
            self.mask.data.masked_fill_(eos_indices, -float('inf'))

        # end condition when all paths reached EOS, so all ones removed from mask
        if (self.mask == 1).nonzero().dim() < 2:
            self.done = True

        # # End condition is when top-of-beam is EOS.
        # if self.nextYs[-1][0] == self.processor.w2i[self.processor.END]:
        #     self.done = True

        return self.done

    def sort_best(self):
        """Sort the beam."""
        return torch.sort(self.scores, 0, True)

    def get_best(self):
        """Get the most likely candidate."""
        scores, ids = self.sort_best()
        return scores[0], ids[0]

    def get_hyp(self, k):
        """
        Walk back to construct the full hypothesis.
        :param k: the position in the beam to construct.
        :return: The hypothesis and The attention at each time step.
        """
        hyp = []
        # print(len(self.prevKs), len(self.nextYs), len(self.attn))
        for j in range(len(self.prevKs) - 1, -1, -1):
            hyp.append(self.nextYs[j + 1][k])
            k = self.prevKs[j][k]

        return hyp[::-1]
