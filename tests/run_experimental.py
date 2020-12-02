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


###############
## Libraries ##
##{{{

import sys,os
import texttable as tt

## Scientific libraries
##=====================

import numpy as np
import scipy.stats as sc
import scipy.optimize as sco
import scipy.linalg as scl
import pandas as pd
import xarray as xr
import SDFC as sd
import SDFC.NonParametric as sdnp

## Plot libraries ##
##==================

import matplotlib as mpl
import matplotlib.pyplot as plt

#mpl.rcParams['font.size'] = 30

##}}}
###############

from experimental.core.__RHS import LHS
from experimental.core.__RHS import RHS
from experimental.link.__Univariate import ULIdentity
from experimental.link.__Univariate import ULExponential
from experimental.link.__Multivariate import MultivariateLink
from experimental.link.__Multivariate import MLLinear
from experimental.link.__Multivariate import MLTensor
from experimental.link.__Normal import NormalRatioLocScaleConstant


from experimental import Normal


###############
## Fonctions ##
###############


#############
## Classes ##
#############


## GEV part
##=========

class GEVPrLink(MultivariateLink):##{{{
	def __init__( self , *args , **kwargs ):
		MultivariateLink.__init__( self , *args , **kwargs )
	
	def transform( self , coef , X ):
		E = np.exp( coef[3] / coef[0] * X[:,0] )
		loc   = coef[0] * E
		scale = coef[1] * E
		shape = coef[2] + np.zeros_like(X[:,0])
		return loc,scale,shape
	
	def jacobian( self , coef , X ):
		E = np.exp( coef[3] / coef[0] * X[:,0] )
		jac = np.zeros( (3 , 4 , X[:,0].size) )
		jac[0,0,:] = E - coef[3] * X[:,0] / coef[0] * E
		jac[1,0,:] = - coef[1] * coef[3] * X[:,0] / coef[0]**2 * E
		jac[1,1,:] = E
		jac[2,2,:] = 1
		jac[0,3,:] = X[:,0] * E
		jac[1,3,:] = coef[1] * X[:,0] * E / coef[0]
		
		return jac
	
	def pseudo_inverse( self , params , lin_coef , X ):
		
		coef = np.zeros(4)
		design = np.stack( (np.ones_like(X),X) , -1 ).squeeze()
		
		idxloc   = np.isfinite(np.log(params[:,0]))
		idxscale = np.isfinite(np.log(params[:,1]))
		resloc   = scl.lstsq( design[idxloc,:]   , np.log(params[idxloc,0]) )
		resscale = scl.lstsq( design[idxscale,:] , np.log(params[idxscale,1]) )
		coef[0] = np.exp(resloc[0][0])
		coef[1] = np.exp(resscale[0][0])
		coef[2] = params[:,2].mean()
		
		alphaloc   = resloc[0][1] * coef[0]
		alphascale = resscale[0][1] * coef[0]
		coef[3]    = ( alphaloc + alphascale ) / 2
		
		return coef
##}}}

class GEV:##{{{
	
	def __init__( self , link , restart_fit = 0 ):##{{{
		self.link  = link
		self.optim = None
		self.coef_ = None
		self.restart_fit = restart_fit
		self.n_restart   = 0
	##}}}
	
	def negloglikelihood( self , coef ): ##{{{
		self.coef_ = coef
		loc,scale,shape = self.link.transform( self.coef_ , self._X )
		return - np.sum( sc.genextreme.logpdf( self._Y , loc = loc , scale = scale , c = -shape ) )
	##}}}

	def grad_nlll( self , coef ): ##{{{
		self.coef_ = coef
		jac = self.link.jacobian( self.coef_ , self._X )
		loc,scale,shape = self.link.transform( self.coef_ , self._X )
		
		
		Z  = ( self._Y - loc ) / scale
		ZZ = 1 + shape * Z
		ZZi = ZZ**( - 1 / shape )
		kappa = ( 1 + 1 / shape ) / ZZ - ZZi / (shape * ZZ)
		
		T0 = - shape * kappa / scale
		T1 = 1 / scale - shape * Z / scale * kappa
		T2 = np.log(ZZ) * ( ZZi - 1 ) / shape**2 + Z * kappa
		
		jac[0,:] *= T0
		jac[1,:] *= T1
		jac[2,:] *= T2
		
		return jac.sum( axis = (0,2) )
	##}}}
	
	def init_mle( self ):##{{{
		sdgev = sd.GEV( method = "lmoments-experimental" )
		sdgev.fit( self._Y , c_loc = np.exp(self._X) , c_scale = np.exp(self._X) )
		params = np.stack( (sdgev.loc,sdgev.scale,sdgev.shape) ).squeeze().T
		minit   = self.link.pseudo_inverse( params , sdgev.coef_ , self._X )
		mcov    = np.identity(4)
		
		## Perturbation if the init point is not well defined
		init = minit.copy()
		nit = 0
		while not np.isfinite(self.negloglikelihood(init)) or not np.isfinite(self.grad_nlll(init).all()):
			init = np.random.multivariate_normal( mean = minit , cov = mcov )
			nit += 1
			if nit % 100 == 0: mcov *= 2
		
		self.coef_ = init
	##}}}
	
	def fit( self , Y , X ):##{{{
		self._Y = Y.squeeze()
		self._X = X.reshape(-1,1) if X.ndim == 1 else X
		self.init_mle()
		self.optim = sco.minimize( self.negloglikelihood , self.coef_ , jac = self.grad_nlll )
		
		restart_init = self.restart_fit
		if not self.optim.success and self.restart_fit > 0:
			self.restart_fit -= 1
			self.fit( Y , X )
		self.n_restart   = restart_init - self.restart_fit
		self.restart_fit = restart_init
		
	##}}}
##}}}

def test_GEV(): ##{{{
	n_samples = 2000
	t,X,_,_ = sd.tools.Dataset.covariates( n_samples )
	X = X.reshape(-1,1)
	l_global = GEVPrLink()
	
	
	coef_true = np.array([0.5,1.5,-0.2,1.3])
	loc,scale,shape = l_global.transform( coef_true , X )
	Y = sc.genextreme.rvs( loc = loc , scale = scale , c = -shape )
	
	gev = GEV( l_global , 10 )
	gev.fit( Y , X )
	
	print(coef_true)
	print(gev.optim.x)
	print(gev.n_restart)
##}}}


## Tests
##======

class NormalTest: ##{{{
	
	def __init__( self , n_sample = 2000 ): ##{{{
		self.n_samples     = n_sample
		t,X_loc,X_scale,_ = sd.tools.Dataset.covariates(self.n_samples)
		self.t       = t
		self.X_loc   = X_loc.reshape(-1,1)
		self.X_scale = X_scale.reshape(-1,1)
	##}}}
	
	def test0( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,1.,0.3,-0.9] )
		self.loc   = self.coef_[0] + self.coef_[1] * self.X_loc
		self.scale = np.exp(self.coef_[2] + self.coef_[3] * self.X_scale)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		
		kwargs = { "c_loc" : self.X_loc , "c_scale" : self.X_scale , "l_scale" : ULExponential() }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test1( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,1.,0.3,-0.9] )
		self.loc   = self.coef_[0] + self.coef_[1] * self.X_loc
		self.scale = np.exp(self.coef_[2] + self.coef_[3] * self.X_scale)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		
		l_global = MLTensor( [MLLinear( c = self.X_loc , l = ULIdentity() ) , MLLinear( c = self.X_scale , l = ULExponential() ) ] , [2,2] , n_samples = self.n_samples , n_features = 4 )
		kwargs = { "c_global" : [self.X_loc,self.X_scale] , "l_global" : l_global }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test2( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,1.,0.3,-0.9] )
		self.loc   = self.coef_[0] + self.coef_[1] * self.X_loc
		self.scale = np.exp(self.coef_[2] + self.coef_[3] * self.X_scale)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		self.coef_ = self.coef_[:2]
		
		kwargs = { "c_loc" : self.X_loc , "f_scale" : self.scale }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test3( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,1.,0.3,-0.9] )
		self.loc   = self.coef_[0] + self.coef_[1] * self.X_loc
		self.scale = np.exp(self.coef_[2] + self.coef_[3] * self.X_scale)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		self.coef_ = self.coef_[2:]
		
		kwargs = { "f_loc" : self.loc , "c_scale" : self.X_scale , "l_scale" : ULExponential() }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test4( self , method = "MLE" ):##{{{
		self.coef_  = np.array([0.8,1.5,2])
		l_global    = NormalRatioLocScaleConstant( self.n_samples )
		self.loc,self.scale = l_global.transform( self.coef_ , self.X_loc )
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		
		kwargs = { "c_global" : [self.X_loc] , "l_global" : l_global }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test5( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,0.3,-0.9] )
		self.loc   = np.repeat( self.coef_[0] , self.n_samples ).reshape(-1,1)
		self.scale = np.exp(self.coef_[1] + self.coef_[2] * self.X_scale)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		
		kwargs = { "c_scale" : self.X_scale , "l_scale" : ULExponential() }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def test6( self , method = "MLE" ):##{{{
		self.coef_ = np.array( [0.5,1.3,-0.9] )
		self.loc   = self.coef_[0] + self.coef_[1] * self.X_loc
		self.scale = np.repeat( np.exp(self.coef_[2]) , self.n_samples ).reshape(-1,1)
		self.Y     = np.random.normal( loc = self.loc , scale = self.scale )
		
		kwargs = { "c_loc" : self.X_loc , "l_scale" : ULExponential() }
		kwargs["prior"] = sc.multivariate_normal( mean = self.coef_ , cov = np.identity(self.coef_.size) )
		self.norm = Normal( method = method )
		self.norm.fit( self.Y , **kwargs )
	##}}}
	
	def summary( self , show = False ): ##{{{
		print( "## => {} / {} / {}".format( np.max(np.abs(self.coef_ - self.norm.coef_)) , self.coef_ , self.norm.coef_ ) )
	##}}}
	
	def run_all( self , method = "MLE" , show = True ):##{{{
		tab = tt.Texttable( max_width = 0 )
		tab.header( ["Normal law test ({})".format(method),"Status","Max diff","True value","Estimated value"] )
		for i in range(7):
			try:
				eval( "self.test{}( method = \"{}\" )".format(i,method) )
				tab.add_row( ["Test {}".format(i),"OK",np.max(np.abs(self.coef_ - self.norm.coef_)) , self.coef_ , np.round(self.norm.coef_,2)] )
			except:
				tab.add_row( ["Test {}".format(i),"Fail","/","/","/"] )
		
		if show: print(tab.draw())
		return tab
	##}}}
	
##}}}


##########
## main ##
##########

if __name__ == "__main__":
	np.seterr( all = "ignore" )
#	np.random.seed(42)
	
	nt = NormalTest()
	nt.run_all("MLE")
	nt.run_all("bayesian")
	
	
	print("Done")



