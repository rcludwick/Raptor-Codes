#!/usr/bin/python

# source object - initial message
# object is broken down into Z >= 1 source blocks - target for a single raptor code application. identified by SBN
# blocks are broken into K source symbols. K is constant for a given object. each symbol has an ESI (encoding symbol identifier)
# size of source symbols: T. (so K*T = block size). 
# sub-blocks are made from EACH block, such that they can be decoded in working memory. N >= 1 subblocks. 
# sublocks have K sub-symbols, of size T'. 

import numpy
import random
import sys
from bitarray import bitarray

# recommended alg values taken from RFC 5053 (basically represents how XOR
# operations are executed, 4 bytes at a time is standard on 32-bit, probably 8
# bytes on 64-bit? if XOR is done on single memory location)
A1 = 4
# min number of symbols per source block, in bytes
Kmin = 1024 
# target size for sub-block, in bytes. let's say 1kb
W = 1024


def precode_identity(symbols):
	# does nothing - takes a list of symbols and returns the same list
	return symbols

def distribution_random_LT(num_symbols):
	# return a vector of coefficient indices sampled from the contained
	# distribution. example return value: [17,22,238]

	# sample a weight from uniform distribution
	d = numpy.random.random_integers(1, num_symbols)

	# construct a vector of d coefficient indices from k. (sampling without
	# replacement. 
	v = random.sample(range(num_symbols),d)
	return v


# one raptor manager is used per object
class RaptorManager:
	def __init__(self, filename, K=1024, debug=True):
		# XXX Currently assumes a string...
		self.debug = debug
		self.f = open(filename, 'rb')
		# number of symbols in each source block
		self.K = K
		# keep a counter blocks get sent out. 
		self.current_block = 0
		# remember how much padding the last block used (not sure we care about
		# this)
		self.padding_last = None
		self.last_block = False

		if self.debug:
			print "registered " +self.f.name+ "."
	
	def _encode_binary_block(self):
		# encode a chunk of size k from the input file as binary and return

		# each character is 8 bits, so divide K by 8 to keep num symbols (bits)
		# commensurate with K. 
		if self.K % 8 != 0:
			sys.stderr.write("error: K must be a byte multiple (ie multiple of 8).")
			return
		n = self.K/8

		block = bitarray()
		start_pos = self.f.tell()
		try:
			block.fromfile(self.f,n)
		except EOFError:
			# if we reach the end of the file, get just the remaining bytes and
			# pad the block as appropriate
			end_pos = self.f.tell()
			remaining_bytes = end_pos - start_pos
			self.f.seek(start_pos)
			block.fromfile(self.f,remaining_bytes)
			padding = self.K - remaining_bytes
			self.padding_last = padding
			self.last_block = True
			block.extend('0'*padding)
		print len(block)
		assert len(block) == self.K
		return block
	
	def num_bits(self, block):
		# block is a bitarray object, which packs bits into longs. so number of
		# bits is the size in bytes * 8. 
		info = block.buffer_info()
		return info[1]*8

	def next_block(self):
		# keep track of where we are and return the next block
		if self.last_block:
			return None
		the_block = self._encode_binary_block()
		self.current_block += 1
		return the_block

class RaptorEncoder:
	def __init__(self, precode, distribution, block, symb_size=1, debug=True):
		# precode and distribution are each function variables
		self.debug = debug
		self.precode_fn = precode 
		self.distribution_fn = distribution
		# symbols is a bitarray()
		self.symbols = block
		if self.debug: print "block has %d symbols"% len(self.symbols)
		# precoded is a bitarray()
		self.precoded = []

	def precode(self):
		# precode function adds redundancy to the source symbols. happens
		# once per block, no matter how many output symbols are generated. 
		self.precoded = self.precode_fn(self.symbols)
		if self.debug: print '%d precoding symbols' % len(self.precoded)

	def generate_encoded(self):

		# distribution_fn must take as argument the number of symbols it is
		# operating over, and return a vector of coefficients indices,
		# sampled according to the distribution therein.
		# example output for 10 precoded symbols: [2,4,9]
		v = self.distribution_fn(len(self.precoded))

		# grab the symbols at the index positions that have a 1 in the
		# coefficient vector.
		selected_symbols = [self.precoded[idx] for idx in v]

		# get the first two values to start the xor process (note this actually
		# removes the values from selected_symbols, so after the for loop below
		# selected_symbols will be in a wierd state and should not be used. 
		if len(selected_symbols) == 1:
			val = selected_symbols.pop()
		else:
			val = selected_symbols.pop()^selected_symbols.pop()
			for val in selected_symbols:
				val = val^val
			
		# return the xor'ed value and the associated coefficients
		return {'val': val, 'coefficients': v}

class RaptorGaussDecoder:

	def __init__(self, K, debug=True):
		self.debug = debug
		self.K = K
		self.A = numpy.array([], dtype=bool)
		self.b = numpy.array([], dtype=bool)
		self.blocks_received = 0

	def add_block(self, encoded):
		val = bool(encoded['val'])
		coeff = encoded['coefficients']
		
		# create a new row vector and set it to one as indicated by the
		# coefficient vector
		new_row = bitarray('0'*self.K)
		for i in range(self.K):
			if i in coeff:
				new_row[i] = 1
			if i > max(coeff):
				break

		# add the new row to the bottom
		if not len(self.A):
			self.A = numpy.array(new_row.tolist())
		else:
			self.A = numpy.vstack((self.A, numpy.array(new_row.tolist())))
		self.b = numpy.append(self.b, val)
		self.blocks_received += 1

	def is_full_rank(self):
		return (numpy.linalg.matrix_rank(self.A) == self.K)

	def get_rank(self):
		return numpy.linalg.matrix_rank(self.A)

	def num_blocks(self):
		# how many encoded blocks have we received so far?
		# this is equivalent to the numer of rows in A. shape() returns (rows, cols)
		return self.A.shape[0]

	def remove_null_rows(self, mat):
		# empty rows
		rows, cols = mat.shape
		all_false = numpy.array([], int)
		for r in xrange(rows):
			if not mat[r,:].any():
				all_false = numpy.append(all_false, r)
				
		to_keep = [r for r in xrange(rows) if r not in all_false]
		return mat[to_keep,:]

	def remove_duplicate_rows(self, mat):
		# duplicates
		duplicates = numpy.array([], int)
		rows, cols = mat.shape
		for r in xrange(rows):
			this_row = mat[r,:]
			for rr in xrange(r+1,rows):
				if rr in duplicates:
					continue
				test_row = mat[rr,:]
				diff = test_row ^ this_row
				if not numpy.any(diff):
					duplicates = numpy.append(duplicates, rr)
		to_keep = [r for r in xrange(rows) if r not in duplicates]

		return mat[to_keep,:]


	def decode_gauss_base2(self):
		# use tmp matrices in case our solution fails. 
		b = numpy.array([self.b])
		mat = numpy.hstack((self.A,b.T))
		tri, b = self._triangularize(mat)
		self._backsub(tri, b)

	def _backsub(self, tri, b):
		mat = numpy.hstack((tri, numpy.array([b]).T))
		rows, cols = tri.shape
		soln = numpy.ones(cols, int)
		for i in (xrange(cols)).__reversed__():
			terms = numpy.logical_and(soln[i:cols],mat[i,i:cols]) 
			# if we successively xor terms with the RHS, we should get the new term
			rhs = mat[i,1]
			for t in terms:
				rhs = rhs ^ t
			soln[i] = rhs
			print "soln for x" + str(i)+" = " + str(soln[i])

		# verify solution:
		print mat
		print "computed solution:"
		print soln


	def _triangularize(self, mat):

		#mat = self.remove_null_rows(mat)
		#mat = self.remove_duplicate_rows(mat)
		rows, cols = mat.shape
		# we tacked the solution vector onto the end of the matrix, so don't
		# count it in terms of the number of columns to iterate over. 
		cols = cols -1
		
		# first, we want to pivot the rows to put A in upper triangular form
		# (get 0's into all columns positions below the given row)
		for c in xrange(0, cols):
			# examine the row values below the diagonal (note that c starts at
			# 1, not 0. so in the first column, go from 1 to rows, in the
			# second column, go from 2.. rows, etc)
			col_vals = mat[c:rows,c]
			if col_vals.max() == 0:
				print "error: below row/column (%d, %d) matrix is singular." % (c,c)
				print mat[c:rows, c:rows]
				return None
			# find first row with a 1 in the left-most column (non-zero returns
			# a tuple, and we want the 0'th element of the first dimension of
			# the tuple since this is just a row vector)
			max_i = col_vals.nonzero()[0][0]

			# do the 'partial pivot': swap rows max_r and c in A and b (unless
			# the current row already has a one, then we're not going to get
			# any better). 
			if not (max_i+c) == c:
				upper_row = mat[c,:]
				lower_row = mat[c+max_i,:]
				mat[c,:] = lower_row
				mat[c+max_i,:] = upper_row

			# now zero out the 1's remaining in this column below the diagonal.
			# get the c'th row (yes, c is also the column value - this ensures
			# we start at the row below the diagonal)
			cth_row = mat[c,:]

			# now for all rows below this one, xor the c'th row with those that
			# contain a 1 in this column, in order to make it 0. (make sure to
			# do this with the right hand solution vector, too). 
			for r in xrange(c+1,rows):
				if mat[r,c] == 1:
					mat[r,:] = (cth_row ^ mat[r,:])
		# end column iteration

		# now we can get rid of the dangling rows since our solution is
		# uniquely specified by the top square component. 
		mat = mat[0:cols,:]

		return mat[:, 0:cols], mat[:, -1]


	def decode_gauss_base10(self):
		# attempt decode
		print "attempting solution..."
		if not self.is_full_rank():
			print "A is not full rank, sorry."
			return None
		soln, residues, rank, sing = numpy.linalg.lstsq(self.A, self.b)
		self.decoded_values = soln 
		return soln, residues, rank, sing

	def convert(self):
		# convert the values back to strings
		bits = bitarray(self.decoded_values.tolist())
		return bits.tostring()
		

class RaptorBPDecoder:
	
	def __init__(self, K):
		self.K = K
		self.symbols_processed = 0
		self.known_symbols = {}
		self.waiting_symbols = []

	def bp_decode(self, block):
		self.symbols_processed += 1
		val = bool(block['val'])
		coeffs = block['coefficients']
		print "coeffs"
		print coeffs
		if len(coeffs) > 1:
			self.reduce(coeffs, val)	
		if len(coeffs) == 1:
			self.process_degree_one(coeffs, val)

		if len(self.known_symbols) == self.K:
			print self.known_symbols
			# return symbols as a bitarray
			return bitarray(self.known_symbols.values())
		else: return None

	def process_degree_one(self,coeff, val):
		self.note_resolved(coeff, val)
		new_resolved = self.match_against_queue(coeff, val)
		while len(new_resolved) > 0:
			new_resolved_copy = new_resolved.copy()
			addtl_resolved = []
			for r in new_resolved_copy:
				self.note_resolved(r['coeffs'][0], r['val'])
				addtl = self.match_against_queue(r['coeffs'][0], r['val'])
				if len(addtl) > 0:
					addtl_resolved.append(addtl)
			new_resolved = addtl_resolved

	def match_against_queue(self,resolved_coeff, resolved_val):
		new_resolved = []
		for w in self.waiting_symbols:
			if resolved_coeff in w['coeffs']:
				w['xor_val'] = w['xor_val'] ^ resolved_val
				w['coeffs'].remove(resolved_coeff)
			if len(w['coeffs']) == 1:
				new_resolved.append(w)
		for r in new_resolved:
			self.waiting_symbols.delete(r)
		return new_resolved

	def note_resolved(self, coeff, val):
		assert len(coeff) == 1
		if not coeff[0] in self.known_symbols.keys():
			self.known_symbols[coeff[0]] = val

	def queue_append(self, coeff, val):
		self.waiting_symbols.append({
			'degree': len(coeff),
			'coeffs': coeff,
			'xor_val': val
		})

	def reduce(self, coeffs, val):
		resolved = []
		for c in coeffs:
			if c in self.known_symbols.keys():
				# xor the known value into the 'data' portion (the xor'ed
				# value)
				val = val ^ self.known_symbols[c]
				resolved.append(c)
		# remove the resolved coefficients
		coeff = [c for c in coeffs if not c in resolved]
		if len(coeffs) == 1:
			self.process_degree_one(coeffs, val)
		else:
			self.queue_append(coeffs, val)

def run_gauss(filename):
	DEBUG = True

	# if we want everything to go in one block, then use len(data) as the block
	# length
	K = 8
	epsilon = int(0.5*8)
	manager = RaptorManager(filename, K)
	block = manager.next_block()
	if DEBUG: 
		print "retrieved block... "
		print block
	# this encoder is non-systematic, uses no pre-code. 
	encoder = RaptorEncoder(precode_identity, distribution_random_LT, block)
	encoder.precode()
	decoder = RaptorGaussDecoder(K)

	# grab new symbols and periodically check to see if we've gathered enough
	# to find a solution. when the decoder matrix is full rank, try and solve
	# for the original symbols. 
	while not decoder.is_full_rank():
		print "not full rank yet, continuing..."
		for i in xrange(K+epsilon):
			e = encoder.generate_encoded()
			decoder.add_block(e)

	print "attempting to solve after " + str(decoder.blocks_received) + " blocks."
	decoder.decode_gauss_base2()
	
	#print decoder.convert()
	print "original block"
	print block

def run_bp(filename):
	DEBUG = True

	# if we want everything to go in one block, then use len(data) as the block
	# length
	K = 8
	epsilon = int(0.5*8)
	manager = RaptorManager(filename, K)

	decoded_blocks = []
	total_overhead = 0
	block = manager.next_block()
	while block:
		print "next block... "
		print block
		# this encoder is non-systematic, uses no pre-code. 
		# XXX it's also weird that there's one encoder per block but one
		# manager and decoder per message. fix. 
		encoder = RaptorEncoder(precode_identity, distribution_random_LT, block)
		decoder = RaptorBPDecoder(K)
		encoder.precode()

		original_symbols = False
		while not original_symbols:
			e = encoder.generate_encoded()
			#print "\n--- NEW encoded block"
			#print e
			original_symbols = decoder.bp_decode(e)
		print block
		print "%d symbols processed for this block for %d source symbols." % (decoder.symbols_processed, K)
		total_overhead = decoder.symbols_processed
		decoded_blocks.append(original_symbols)
		block = manager.next_block()
	
	print "decoder processed %d blocks with %f%% average overhead" % (len(decoded_blocks), 100*total_overhead/float(len(decoded_blocks)))
	print "original message was"
	print decoded_blocks
	for d in decoded_blocks:
		sys.stdout.write(d.tostring())

	
if __name__ == '__main__':
	if len(sys.argv) != 2:
		sys.stderr.write("Usage: ./raptor filename")
		sys.exit(1)
	filename = sys.argv[1]
	run_gauss(filename)
	#run_bp(filename)




