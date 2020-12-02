# -*- coding: utf-8 -*-

## Copyright(c) 2020 Yoann Robin
## 
## This file is part of SDFC.
## 
## SDFC is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
## 
## SDFC is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
## 
## You should have received a copy of the GNU General Public License
## along with SDFC.  If not, see <https://www.gnu.org/licenses/>.


##############
## Packages ##
##############

import numpy        as np
import scipy.linalg as scl

from ..link.__Univariate import ULIdentity


###############
## Functions ##
###############

def var( Y , c_Y = None , m_Y = None , link = ULIdentity() , value = True ):
	"""
		SDFC.NonParametric.var
		======================
		
		Estimate variance given a covariate (or not)
		
		Parameters
		----------
		Y     : np.array
			Dataset to fit the mean
		c_Y   : np.array or None
			Covariate(s)
		m_Y   : np.array or float or None
			mean of Y. If None, m = np.mean(Y)
		link  : class based on SDFC.tools.Link
			Link function, default is identity
		value : bool
			If true return value fitted, else return coefficients of fit
		
		Returns
		-------
		The variance
	"""
	out,coef = None,None
	if c_Y is None:
		out  = np.var(Y)
		coef = link.inverse(out)
	else:
		m_Y = np.mean( Y , axis = 0 ) if m_Y is None else np.array( [m_Y] ).reshape(-1,1)
		Yres = ( Y - m_Y )**2
		if c_Y.ndim == 1: c_Y = c_Y.reshape(-1,1)
		design = np.hstack( ( np.ones((Y.size,1)) , c_Y ) )
		coef,_,_,_ = scl.lstsq( design , link.inverse( Yres ) )
		out = np.abs( link( design @ coef ) )
	
	return out if value else coef



